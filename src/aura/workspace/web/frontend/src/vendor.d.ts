/// <reference types="vite/client" />

declare module "cascade-core" { export class CascadeEngine { constructor(options:{workerUrl:string}); init():Promise<void>; evaluate(code:string,options?:{maxDeviation?:number}):Promise<any>; dispose():void } }
