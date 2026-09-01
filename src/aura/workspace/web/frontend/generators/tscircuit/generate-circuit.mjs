import { performance } from "node:perf_hooks"
import { Battery, Board, Chip, Circuit, Diode, Mosfet, Resistor, Trace } from "@tscircuit/core"

const started = performance.now()
const readInput = async () => {
  const chunks = []
  for await (const chunk of process.stdin) chunks.push(chunk)
  return JSON.parse(Buffer.concat(chunks).toString("utf8"))
}
const rejectExecutable = value => {
  if (Array.isArray(value)) return value.some(rejectExecutable)
  if (!value || typeof value !== "object") return false
  return Object.entries(value).some(([key, child]) => ["code","script","javascript","command","executable"].includes(key.toLowerCase()) || rejectExecutable(child))
}
const fail = message => { process.stderr.write(JSON.stringify({status:"failed",error:message})); process.exit(2) }

try {
  const request = await readInput()
  if (rejectExecutable(request)) fail("Executable fields are forbidden")
  if (!Array.isArray(request.components) || request.components.length < 1 || request.components.length > 100) fail("Component count must be 1-100")
  if (!Array.isArray(request.connections)) fail("Connections must be an array")
  const circuit = new Circuit(); const board = new Board({width:"80mm",height:"50mm"}); circuit.add(board)
  const sourceByReference = new Map()
  for (const component of request.components) {
    const common = {name:component.reference,displayName:component.displayName}
    const pinLabels=Object.fromEntries(component.pins.map((pin,index)=>[index+1,pin]))
    let instance
    if (component.kind === "controller") instance = new Chip({...common,footprint:"soic8",pinLabels})
    else if (component.kind === "generic_sensor") instance = new Chip({...common,footprint:"sot23",pinLabels})
    else if (component.kind === "generic_actuator") instance = new Chip({...common,footprint:"sot23",pinLabels})
    else if (component.kind === "generic_module") instance = new Chip({...common,footprint:"soic8",pinLabels})
    // Legacy kinds remain readable for older persisted artifacts.  New graph
    // compilation emits semantic generic blocks instead of resistor stand-ins.
    else if (component.kind === "soil_sensor") instance = new Chip({...common,footprint:"sot23",pinLabels})
    else if (component.kind === "mosfet") instance = new Mosfet({...common,channelType:"n",mosfetMode:"enhancement",footprint:"sot23"})
    else if (component.kind === "diode") instance = new Diode({...common,footprint:"sod123"})
    else if (component.kind === "resistor") instance = new Resistor({...common,resistance:"10k",footprint:"0402"})
    else if (component.kind === "servo") instance = new Chip({...common,footprint:"sot23",pinLabels})
    else if (component.kind === "motor") instance = new Chip({...common,footprint:"sot23",pinLabels})
    else if (component.kind === "power_source") instance = new Battery({...common,capacity:"2000mAh"})
    else fail(`Unsupported component kind: ${component.kind}`)
    board.add(instance); sourceByReference.set(component.reference, component)
  }
  for (const connection of request.connections) {
    const [fromRef,fromPin]=connection.from.split(".")
    const [toRef,toPin]=connection.to.split(".")
    const fromComponent=sourceByReference.get(fromRef),toComponent=sourceByReference.get(toRef)
    const fromNumber=fromComponent.pins.indexOf(fromPin)+1,toNumber=toComponent.pins.indexOf(toPin)+1
    board.add(new Trace({from:`.${fromRef} > .pin${fromNumber}`,to:`.${toRef} > .pin${toNumber}`}))
  }
  const circuitJson = circuit.getCircuitJson()
  circuitJson.filter(e=>e.type==="schematic_trace").forEach((trace,index)=>{trace.aura_connection=request.connections[index];trace.aura_graph_connection_id=request.connections[index]?.graphConnectionId})
  request.connections.forEach((item,index)=>circuitJson.push({type:"aura_electrical_connection",aura_electrical_connection_id:`electrical_${index}`,status:"connected",...item}))
  request.unconnected?.forEach((item,index)=>circuitJson.push({type:"aura_unconnected_interface",aura_unconnected_interface_id:`unconnected_${index}`,...item}))
  const namesBySource = new Map(circuitJson.filter(e=>e.type==="source_component").map(e=>[e.source_component_id,e.name]))
  for (const element of circuitJson.filter(e=>e.type==="schematic_component")) {
    const reference=namesBySource.get(element.source_component_id); const index=request.components.findIndex(c=>c.reference===reference)
    if(index<0) continue
    const component=sourceByReference.get(reference);element.aura_semantic_id=component.semanticId
    element.aura_display_name=component.displayName;element.symbol_display_value=component.displayName
    element.aura_component_definition_id=component.componentDefinitionId
  }
  for (const element of circuitJson.filter(e=>e.type==="source_component")) {
    const reference=element.name,component=sourceByReference.get(reference)
    if(!component) continue
    element.aura_reference=reference;element.display_name=component.displayName
    element.name=`${reference} ${component.displayName}`
  }
  const mapping=Object.fromEntries(request.components.map(component=>[component.reference,component.semanticId]))
  const generationMs=performance.now()-started
  process.stdout.write(JSON.stringify({status:"ready",circuitJson,semanticMapping:mapping,warnings:[],metrics:{generationMs}}))
} catch(error) { fail(error instanceof Error ? error.message : String(error)) }
