import {describe,expect,it} from "vitest";
import {WorkspaceSession} from "./workspaceSession";
describe("WorkspaceSession",()=>{
 it("rejects A after switching to B",()=>{const s=new WorkspaceSession(),a=s.begin("A"),b=s.begin("B");expect(s.accept(a,1)).toBe(false);expect(s.accept(b,2)).toBe(true);expect(s.identity).toEqual({projectId:"B",revision:2})});
 it("invalidates work when cleared",()=>{const s=new WorkspaceSession(),t=s.begin("A");s.clear();expect(s.accept(t)).toBe(false)});
});
