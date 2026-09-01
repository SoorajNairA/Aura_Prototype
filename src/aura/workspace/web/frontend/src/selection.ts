export type SelectionSource="3d"|"schematic"|"hierarchy"|"narration"|"evidence"|"programmatic";
export type SelectionKind="component"|"net";
export type Selection={kind:SelectionKind;id:string};
export type SelectionState={selection:Selection|null;selectedSemanticId:string|null;hoveredSemanticId:string|null;auraFocusSemanticIds:string[]};
export type SelectionEvent={source:SelectionSource;semanticId:string|null;kind:SelectionKind;previous:string|null;next:string|null;timestamp:number};

export class SelectionStore {
  private state:SelectionState={selection:null,selectedSemanticId:null,hoveredSemanticId:null,auraFocusSemanticIds:[]};
  private listeners=new Set<(state:SelectionState,event:SelectionEvent)=>void>();
  private events:SelectionEvent[]=[];
  get snapshot(){return this.state}
  get subscriberCount(){return this.listeners.size}
  get eventCount(){return this.events.length}
  select(semanticId:string|null,source:SelectionSource,kind:SelectionKind="component"){
    const previous=this.state.selectedSemanticId;
    if(previous===semanticId&&this.state.selection?.kind===kind)return;
    this.state={...this.state,selection:semanticId?{kind,id:semanticId}:null,selectedSemanticId:semanticId};
    const event={source,semanticId,kind,previous,next:semanticId,timestamp:Date.now()};
    this.events.push(event);this.emit(event);
  }
  hover(semanticId:string|null){this.state={...this.state,hoveredSemanticId:semanticId}}
  focus(ids:string[]){this.state={...this.state,auraFocusSemanticIds:[...new Set(ids)]}}
  reset(){this.state={selection:null,selectedSemanticId:null,hoveredSemanticId:null,auraFocusSemanticIds:[]}}
  subscribe(listener:(state:SelectionState,event:SelectionEvent)=>void){this.listeners.add(listener);return()=>{this.listeners.delete(listener)}}
  private emit(event:SelectionEvent){for(const listener of this.listeners)listener(this.state,event)}
}
