import {expect,test} from "@playwright/test";

const enabled=process.env.AURA_RUNTIME_REHEARSAL==="1";
const base=(process.env.AURA_REHEARSAL_URL||"http://127.0.0.1:8765").replace(/\/$/,"");
const objectives=[
 "Build a tabletop two-axis solar tracker that automatically points a small solar panel toward the brightest light source using an Arduino Nano.",
 "Build an Arduino Nano controlled tabletop DC fan with adjustable speed.",
 "Build a remote-controlled four-wheel rover with a microcontroller, motor driver, battery, and DC gear motors.",
 "Build an Arduino Nano system that turns on a small DC water pump when soil moisture becomes low.",
 "Build an Arduino system that uses a relay module to switch a low-voltage lamp.",
];

test("five-project 3d credibility runtime rehearsal",async({page,request})=>{
 test.skip(!enabled,"Set AURA_RUNTIME_REHEARSAL=1 for the explicit release rehearsal.");
 test.setTimeout(240_000);const results:any[]=[];
 await page.goto(base);await expect(page.getByText("What do you want to build?")).toBeVisible();
 for(const [index,objective] of objectives.entries()){
  const created=await request.post(`${base}/api/projects`,{data:{objective,planningMode:"deterministic_test",operationId:`runtime-rehearsal-${index}-${Date.now()}`}});expect(created.ok()).toBe(true);const createdProject=await created.json();
  await page.goto(`${base}/?projectId=${createdProject.projectId}`);
  await expect(page.getByTestId("engineering-space")).toBeVisible({timeout:45_000});
  await expect.poll(()=>page.evaluate(()=>(window as any).__auraSceneMetrics?.()?.activeProjectId||null),{timeout:45_000}).not.toBeNull();
  const metrics=await page.evaluate(()=>(window as any).__auraSceneMetrics());
  expect(metrics.visibleMeshes).toBeGreaterThan(0);expect(metrics.finiteBounds).toBe(true);expect(metrics.contextLost).toBe(false);
  const projectId=metrics.activeProjectId,project=(await request.get(`${base}/api/projects/${projectId}`));expect(project.ok()).toBe(true);const body=await project.json();
  expect(body.status).not.toBe("build_incomplete");expect(body.revision).toBeGreaterThan(0);
  const [graph,assembly,verification]=await Promise.all([request.get(`${base}/api/projects/${projectId}/graph`).then(r=>r.json()),request.get(`${base}/api/projects/${projectId}/assembly`).then(r=>r.json()),request.get(`${base}/api/projects/${projectId}/verification`).then(r=>r.json())]);
  expect(graph.project_id).toBe(projectId);expect(assembly.parts.length).toBeGreaterThan(0);expect(assembly.unresolvedPrimaryMechanism).toEqual([]);expect(verification.summary.failed||0).toBe(0);
  if(index===2){const wheels=assembly.parts.filter((item:any)=>item.family==="drive_wheel"),motors=assembly.parts.filter((item:any)=>item.family==="small_dc_motor"),chassis=assembly.parts.find((item:any)=>item.family==="mounting_plate"),electronics=assembly.parts.filter((item:any)=>["microcontroller_board","motor_driver","low_voltage_power_source","wireless_module"].includes(item.family));expect(wheels).toHaveLength(4);expect(motors).toHaveLength(4);expect(new Set(wheels.map((item:any)=>Math.round(item.assembledTransform.position[0]))).size).toBe(2);expect(new Set(wheels.map((item:any)=>Math.round(item.assembledTransform.position[1]))).size).toBe(2);expect(electronics.every((item:any)=>Math.abs(item.assembledTransform.position[0]-chassis.assembledTransform.position[0])<=chassis.dimensions[0]/2)).toBe(true);const before=await page.evaluate(()=>(window as any).__auraSceneMetrics().bounds);await page.getByRole("button",{name:"EXPLODE"}).click();await page.getByRole("button",{name:"ASSEMBLE"}).click();const after=await page.evaluate(()=>(window as any).__auraSceneMetrics().bounds);expect(after).toEqual(before)}
  const slug=["solar-tracker","dc-fan","remote-car","soil-pump","relay-lamp"][index];
  await page.screenshot({path:`test-results/aura-rehearsal/${slug}-assembly.png`,fullPage:true});
  await page.getByRole("button",{name:"SCHEMATIC",exact:true}).click();await expect(page.getByTestId("schematic")).toBeVisible();await expect(page.locator("[data-schematic-component-id]").first()).toBeVisible();
  await page.screenshot({path:`test-results/aura-rehearsal/${slug}-schematic.png`,fullPage:true});
  await page.getByRole("button",{name:"SPLIT",exact:true}).click();await page.getByRole("button",{name:"ASSEMBLY",exact:true}).click();
  await page.locator(".semantic-parts button[aria-label]").first().click();await expect(page.getByTestId("selected")).not.toHaveText("");
  const finalProject=await request.get(`${base}/api/projects/${projectId}`).then(r=>r.json()),components=graph.entities.filter((item:any)=>item.kind==="component"),nets=graph.entities.filter((item:any)=>item.metadata?.semantic_type==="electrical_net");results.push({objective,projectId,revision:finalProject.revision,status:finalProject.status,planningMode:finalProject.planningMode,metrics,components:components.length,electricalComponents:components.filter((item:any)=>item.metadata?.interfaces?.some((port:string)=>["power","ground","signal","load-output"].includes(port))).length,nets:nets.length,wires:assembly.wireCount||0,unresolved:assembly.physicalRepresentationLimitations?.length||0,verification:verification.summary});
 }
 await page.getByRole("button",{name:/PROJECT/}).click();await page.getByTestId("projects-panel").getByRole("button",{name:new RegExp(objectives[0],"i")}).click();
 await expect.poll(()=>page.evaluate(()=>(window as any).__auraSceneMetrics?.()?.activeProjectId||null)).toBe(results[0].projectId);
 console.log("AURA_RUNTIME_REHEARSAL",JSON.stringify(results));
});
