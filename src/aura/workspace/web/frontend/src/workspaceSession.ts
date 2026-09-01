export type WorkspaceIdentity={projectId:string;revision:number};

/** Owns the single visible workspace session and rejects late async results. */
export class WorkspaceSession {
 private generation=0;
 identity:WorkspaceIdentity|null=null;
 begin(projectId:string){this.generation+=1;this.identity={projectId,revision:0};return {projectId,generation:this.generation}}
 accept(token:{projectId:string;generation:number},revision?:number){const valid=token.generation===this.generation&&token.projectId===this.identity?.projectId;if(valid&&revision!==undefined)this.identity={projectId:token.projectId,revision};return valid}
 clear(){this.generation+=1;this.identity=null}
}
