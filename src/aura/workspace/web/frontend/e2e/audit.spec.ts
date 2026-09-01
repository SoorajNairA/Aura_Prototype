import {expect,test,Page} from "@playwright/test";

const part=(projectId:string)=>({semanticId:"component-controller",label:`${projectId} controller`,subsystem:"electronics",parentAssembly:projectId,representationSource:"conceptual procedural model",dimensions:[52,28,8],assembledTransform:{position:[0,0,8]},explodedTransform:{position:[0,0,20]},verificationState:"conceptual"});
const project=(id:string,artifactId:string)=>({projectId:id,objective:`build ${id} system`,revision:1,status:"ready",planningMode:"deterministic_test",capability:{status:"SUPPORTED"},representations:[{type:"circuit_schematic",artifactId}]});
const circuit=(id:string)=>[{type:"schematic_component",schematic_component_id:`schematic_${id}`,source_component_id:`source_${id}`,center:{x:0,y:0},size:{width:1.5,height:.8},symbol_name:"boxresistor_right",symbol_display_value:id,is_box_with_pins:true,rotation:0,aura_semantic_id:"component-controller"}];

async function projectRoutes(page:Page,delayA=800){
 const projects=[project("project-a","circuit-a"),project("project-b","circuit-b")];
 await page.route("**/api/projects",route=>route.fulfill({json:projects}));
 for(const p of projects){
  await page.route(`**/api/projects/${p.projectId}`,route=>route.fulfill({json:p}));
  await page.route(`**/api/projects/${p.projectId}/assembly`,route=>route.fulfill({json:{parts:[part(p.projectId)],connectors:[],relationships:[]}}));
  await page.route(`**/api/projects/${p.projectId}/graph`,route=>route.fulfill({json:{project_id:p.projectId,entities:[{id:p.projectId,kind:"project",name:p.projectId},{id:"component-controller",kind:"component",name:`${p.projectId} controller`}],relationships:[]}}));
  await page.route(`**/api/projects/${p.projectId}/verification`,route=>route.fulfill({json:{summary:{failed:0},findings:[]}}));
  await page.route(`**/api/projects/${p.projectId}/narrations`,route=>route.fulfill({json:[]}));
  await page.route(`**/api/projects/${p.projectId}/revisions`,route=>route.fulfill({json:[{revision:1,summary:"created"}]}));
 }
 await page.route("**/api/artifacts/circuit-a/content",async route=>{if(delayA)await new Promise(resolve=>setTimeout(resolve,delayA));await route.fulfill({json:circuit("A")})});
 await page.route("**/api/artifacts/circuit-b/content",route=>route.fulfill({json:circuit("B")}));
}

test("late old-project artifact cannot overwrite the active scene or schematic",async({page})=>{
 await projectRoutes(page);await page.goto("/?projectId=project-a");
 await expect(page.getByRole("button",{name:/PROJECT project-a/i})).toBeVisible();
 await page.getByRole("button",{name:/project-a/i}).first().click();
 await page.getByTestId("projects-panel").getByRole("button",{name:/build project-b system/i}).click();
 await expect(page.getByRole("button",{name:/PROJECT project-b/i})).toBeVisible();
 await page.getByRole("button",{name:"SCHEMATIC"}).click();
 await page.waitForTimeout(1000);
 const metrics=await page.evaluate(()=>(window as any).__auraSceneMetrics());
 expect(metrics.activeProjectId).toBe("project-b");
 await expect(page.locator('[data-schematic-component-id="schematic_B"]')).toBeVisible();
 await expect(page.locator('[data-schematic-component-id="schematic_A"]')).toHaveCount(0);
});

test("returning to welcome invalidates late project hydration",async({page})=>{
 await projectRoutes(page);await page.goto("/?projectId=project-a");
 await expect(page.getByRole("button",{name:/PROJECT project-a/i})).toBeVisible();
 await page.getByRole("button",{name:"AURA"}).click();
 await expect(page.getByText("What do you want to build?")).toBeVisible();
 await page.waitForTimeout(1000);
 await expect(page.getByText("What do you want to build?")).toBeVisible();
 expect(await page.evaluate(()=>(window as any).__auraSceneMetrics)).toBeUndefined();
});

test("fifty project switches and twenty view cycles retain one bounded renderer",async({page})=>{
 await projectRoutes(page,0);await page.goto("/?projectId=project-a");await expect(page.getByRole("button",{name:/PROJECT project-a/i})).toBeVisible();
 const baseline=await page.evaluate(()=>(window as any).__auraSceneMetrics());
 for(let index=0;index<50;index++){
  const next=index%2?"project-a":"project-b";
  await page.getByRole("button",{name:/PROJECT project-[ab]/i}).click();
  await page.getByTestId("projects-panel").getByRole("button",{name:new RegExp(`build ${next} system`,"i")}).click();
  await expect(page.getByRole("button",{name:new RegExp(`PROJECT ${next}`,"i")})).toBeVisible();
 }
 for(let index=0;index<20;index++)for(const mode of ["SCHEMATIC","SPLIT","ASSEMBLY"])await page.getByRole("button",{name:mode,exact:true}).click();
 await page.waitForTimeout(500);const metrics=await page.evaluate(()=>(window as any).__auraSceneMetrics());
 expect(metrics.activeProjectId).toBe("project-a");expect(metrics.finiteBounds).toBe(true);expect(metrics.visibleMeshes).toBeGreaterThan(0);expect(metrics.rendererGeometries).toBeLessThanOrEqual(baseline.rendererGeometries+4);await expect(page.locator("canvas")).toHaveCount(1);
});

test("an old-project reconnect timer cannot reopen its socket after a switch",async({page})=>{
 await page.addInitScript(()=>{
  class AuditSocket{
   static instances:AuditSocket[]=[];onopen:(()=>void)|null=null;onmessage:((event:{data:string})=>void)|null=null;onclose:(()=>void)|null=null;url:string;
   constructor(url:string){this.url=url;AuditSocket.instances.push(this);setTimeout(()=>this.onopen?.(),0)}
   close(){this.onclose?.()}
  }
  ;(window as any).WebSocket=AuditSocket;(window as any).__auditSockets=AuditSocket.instances;
 });
 await projectRoutes(page,0);await page.goto("/?projectId=project-a");await expect(page.getByRole("button",{name:/PROJECT project-a/i})).toBeVisible();
 await page.evaluate(()=>{const socket=(window as any).__auditSockets[0];socket.onclose?.()});
 await page.getByRole("button",{name:/PROJECT project-a/i}).click();await page.getByTestId("projects-panel").getByRole("button",{name:/build project-b system/i}).click();await expect(page.getByRole("button",{name:/PROJECT project-b/i})).toBeVisible();
 await page.waitForTimeout(2300);const urls=await page.evaluate(()=>(window as any).__auditSockets.map((socket:any)=>socket.url));
 expect(urls).toHaveLength(2);expect(urls[0]).toContain("project-a");expect(urls[1]).toContain("project-b");
});

test("WebGL context loss is visible and restoration is reported",async({page})=>{
 await projectRoutes(page,0);await page.goto("/?projectId=project-a");await expect(page.getByRole("button",{name:/PROJECT project-a/i})).toBeVisible();
 await page.locator("canvas").dispatchEvent("webglcontextlost");await expect(page.locator(".narration-card")).toContainText("3D representation interrupted");
 await page.locator("canvas").dispatchEvent("webglcontextrestored");await expect(page.locator(".narration-card")).toContainText("3D renderer restored");
});

test("a missing restored project recovers to the launcher without a blank renderer",async({page})=>{
 const errors:string[]=[];page.on("pageerror",error=>errors.push(error.message));
 await page.route("**/api/projects/project-stale**",route=>route.fulfill({status:404,json:{detail:"Project not found"}}));
 await page.route("**/api/projects",route=>route.fulfill({json:[]}));
 await page.goto("/?projectId=project-stale");
 await expect(page.getByText("What do you want to build?")).toBeVisible();
 await expect(page.getByText("That saved project is no longer available. Start a new design.")).toBeVisible();
 await expect(page.locator("#root")).not.toBeEmpty();
 expect(errors).toEqual([]);
 expect(new URL(page.url()).search).toBe("");
});
