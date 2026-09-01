from __future__ import annotations

from dataclasses import dataclass
from math import acos, cos, degrees, radians, sin, sqrt
from typing import Any

from aura.engineering_graph.model import EngineeringEntity, EngineeringGraph, EntityKind
from aura.engineering_graph.interfaces import component_interfaces, interface_dict
from aura.engineering_graph.electrical import electrical_nets


@dataclass(frozen=True)
class PhysicalPart:
    semantic_id: str
    label: str
    subsystem: str
    parent: str
    source: str
    dimensions: tuple[float, float, float]
    assembled: tuple[float, float, float]
    exploded: tuple[float, float, float]
    rotation: tuple[float, float, float, float] = (0,0,0,1)
    verification: str = "estimated"
    family: str = ""
    transform_source: str = "INDEPENDENT_LAYOUT"
    functional_roles: tuple[str, ...] = ()
    generator_family: str = "family-aware-proxy"
    representation_class: str = "conceptual"
    output_axis: tuple[float, float, float] | None = None
    visual_kind: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"semanticId":self.semantic_id,"label":self.label,"subsystem":self.subsystem,
            "parentAssembly":self.parent,"representationSource":self.source,"dimensions":list(self.dimensions),
            "assembledTransform":{"position":list(self.assembled),"rotation":list(self.rotation)},
            "explodedTransform":{"position":list(self.exploded),"rotation":list(self.rotation)},
            "verificationState":self.verification,"family":self.family,"functionalRoles":list(self.functional_roles),
            "transformSource":self.transform_source,"generatorFamily":self.generator_family,
            "representationClass":self.representation_class,"representationFeatures":list(_representation_features(self.family)),
            "representationParameters":_representation_parameters(self.family,self.dimensions),
            "outputAxis":list(self.output_axis) if self.output_axis else None,"visualKind":self.visual_kind or self.family}


def engineering_assembly(graph:EngineeringGraph)->dict[str,Any]:
    components=graph.find(kind=EntityKind.COMPONENT);groups:dict[str,list[EngineeringEntity]]={}
    for entity in components:groups.setdefault(entity.parent_id or "conceptual",[]).append(entity)
    parts=[];hierarchy={}
    for group_index,(parent,items) in enumerate(sorted(groups.items())):
        hierarchy[parent]=[item.id for item in items]
        for index,entity in enumerate(items):
            meta=entity.metadata;family=meta.get("family",meta.get("role","generic_mechanical_part"));dims=meta.get("dimensions",{})
            dimensions=tuple(float(dims.get(key,{}).get("value",fallback)) for key,fallback in (("width",45),("length",30),("height",18)))
            role=str(meta.get("subsystem",parent.removeprefix("subsystem-")))
            # This grid is reserved for non-mechanical secondary components.
            # Mechanism members are replaced below by topology-derived roots and
            # interface-mated transforms.
            ordinal=len(parts);assembled=(220.0+(ordinal%3)*70.0,(ordinal//3)*55.0,dimensions[2]/2)
            exploded=(assembled[0]+45+(ordinal%3)*20,assembled[1]*1.35,assembled[2]+55)
            resolution=str(meta.get("parameters",{}).get("resolution_quality","CONCEPTUAL"));representation_class="exact" if resolution=="EXACT" else "generic" if resolution=="COMPATIBLE_GENERIC" else "conceptual"
            source="family-aware procedural representation"
            roles=tuple(str(value) for value in meta.get("parameters",{}).get("functional_roles",()))
            output_axis=tuple(float(value) for value in meta.get("parameters",{}).get("output_axis",())) or None
            visual_kind=str(meta.get("parameters",{}).get("visual_template") or meta.get("parameters",{}).get("surface_kind",family))
            parts.append(PhysicalPart(entity.id,entity.name,role,parent,source,dimensions,assembled,exploded,(0,0,0,1),"conceptual",family,"INDEPENDENT_LAYOUT",roles,f"{family or 'unknown'}-proxy",representation_class,output_axis,visual_kind))
    by_id={part.semantic_id:part for part in parts};interfaces=[];by_owner={}
    for entity in components:
        part=by_id[entity.id];family=entity.metadata.get("family",entity.metadata.get("role",""))
        definitions=component_interfaces(family,part.dimensions,entity.metadata.get("parameters",{}));by_owner[entity.id]=definitions
        interfaces.extend(interface_dict(entity.id,item) for item in definitions)
    positions={part.semantic_id:list(part.assembled) for part in parts};rotations={part.semantic_id:(0.,0.,0.,1.) for part in parts};mated=[];constraints=[];used=set();placement={part.semantic_id:"INDEPENDENT_LAYOUT" for part in parts};unresolved=[]
    connection_entities={entity.id:entity for entity in graph.find(kind=EntityKind.CONNECTION)}
    mechanical={"mechanical","fixed","revolute","hinge"}
    for relation in graph.relationships.values():
        if relation.type not in mechanical or relation.source_id not in by_owner or relation.target_id not in by_owner: continue
        connection=connection_entities.get(str(relation.metadata.get("connection_id","")))
        metadata=connection.metadata if connection else {}
        exact=((a,b) for a in by_owner[relation.source_id] for b in by_owner[relation.target_id]
               if a.name==metadata.get("source_interface") and b.name==metadata.get("target_interface"))
        compatible=((a,b) for a in by_owner[relation.source_id] for b in by_owner[relation.target_id] if b.kind in a.compatible)
        pair=next((candidate for candidate in (*exact,*compatible)
                   if candidate[1].kind in candidate[0].compatible and f"{relation.source_id}:{candidate[0].name}" not in used and f"{relation.target_id}:{candidate[1].name}" not in used),None)
        if not pair:
            unresolved.append({"relationshipId":relation.id,"sourceId":relation.source_id,"targetId":relation.target_id,"reason":"no unused compatible interface pair"});continue
        source,target=pair
        source_id=f"{relation.source_id}:{source.name}";target_id=f"{relation.target_id}:{target.name}";used.update((source_id,target_id))
        constraints.append((relation.id,relation.source_id,source,relation.target_id,target))
        mate_type="revolute" if source.kind in {"rotating_output","hinge_axis"} else "prismatic" if source.kind=="linear_output" else "fixed"
        mated.append({"from":source_id,"to":target_id,"type":mate_type})

    # Solve the directed mate graph from deterministic structural roots.  This
    # is independent of project names, subsystem columns, or component centres.
    outgoing:dict[str,list[tuple[str,str,Any,str,Any]]]={part.semantic_id:[] for part in parts}
    incoming={part.semantic_id:0 for part in parts};undirected={part.semantic_id:set() for part in parts}
    for constraint in constraints:
        _,source_owner,_,target_owner,_=constraint
        outgoing[source_owner].append(constraint);incoming[target_owner]+=1
        undirected[source_owner].add(target_owner);undirected[target_owner].add(source_owner)
    mechanical_ids={component_id for component_id,neighbors in undirected.items() if neighbors}
    unseen=set(mechanical_ids);connected_groups=[]
    while unseen:
        seed=min(unseen);group={seed};pending=[seed];unseen.remove(seed)
        while pending:
            current=pending.pop()
            for neighbor in sorted(undirected[current] & unseen):
                unseen.remove(neighbor);group.add(neighbor);pending.append(neighbor)
        connected_groups.append(group)
    placed=set();visualization_pose=[];joint_pose_index=0
    for group_index,group in enumerate(sorted(connected_groups,key=lambda item:min(item))):
        roots=sorted(component_id for component_id in group if incoming[component_id]==0)
        if not roots:
            cycle=sorted(group)
            unresolved.append({"relationshipId":None,"sourceId":cycle[0],"targetId":cycle[-1],"reason":"directed mechanical mate cycle"})
            for offset,component_id in enumerate(cycle):
                positions[component_id]=[group_index*220.0,offset*70.0,by_id[component_id].dimensions[2]/2]
                placement[component_id]="CONCEPTUAL_TOPOLOGY"
            continue
        for root_index,root in enumerate(roots):
            positions[root]=[group_index*220.0,root_index*80.0,by_id[root].dimensions[2]/2]
            placement[root]="FIXED_ROOT";placed.add(root)
        pending=list(roots)
        while pending:
            source_owner=pending.pop(0)
            for relationship_id,_source_owner,source,target_owner,target in sorted(outgoing[source_owner],key=lambda item:item[0]):
                if target_owner in placed:
                    continue
                source_offset=_rotate(rotations[source_owner],source.position)
                source_world=[positions[source_owner][i]+source_offset[i] for i in range(3)]
                if source.axis and target.axis:
                    source_axis=_rotate(rotations[source_owner],source.axis)
                    desired=source_axis if source.kind in {"rotating_output","hinge_axis","linear_output"} else tuple(-value for value in source_axis)
                    rotations[target_owner]=_from_to(target.axis,desired)
                    if source.name.startswith("drive-mount-") and by_id[target_owner].family=="small_dc_motor" and source.position[1]>0:
                        rotations[target_owner]=_quat_multiply(_axis_angle((0,0,1),radians(180)),rotations[target_owner])
                    if source.kind in {"rotating_output","hinge_axis"}:
                        angle=(18.,-24.,22.,-16.)[joint_pose_index%4];joint_pose_index+=1
                        rotations[target_owner]=_quat_multiply(_axis_angle(source_axis,radians(angle)),rotations[target_owner])
                        visualization_pose.append({"componentId":target_owner,"relationshipId":relationship_id,"jointType":"revolute","angleDegrees":angle,"source":"DETERMINISTIC_DEFAULT"})
                clearance=max(source.clearance_mm,target.clearance_mm)
                target_offset=_rotate(rotations[target_owner],target.position)
                positions[target_owner]=[source_world[i]-target_offset[i]+(source_axis[i] if source.axis else 0)*clearance for i in range(3)]
                placement[target_owner]="MATE_SOLVED";placed.add(target_owner);pending.append(target_owner)
        unreachable=sorted(group-placed)
        for component_id in unreachable:
            placement[component_id]="CONCEPTUAL_TOPOLOGY"
            unresolved.append({"relationshipId":None,"sourceId":roots[0],"targetId":component_id,"reason":"mate topology is not reachable from a root"})

    role_index={entity.id:set(entity.metadata.get("parameters",{}).get("functional_roles",())) for entity in components}
    parameter_index={entity.id:entity.metadata.get("parameters",{}) for entity in components}
    actuator_ids={component_id for component_id,roles in role_index.items() if "controlled_motion" in roles}
    moving_ids={component_id for component_id,roles in role_index.items() if {"moving_surface","moving_body","drive_output","motion_transmission"}&roles}
    axis_ids={component_id for component_id,parameters in parameter_index.items() if parameters.get("controlled_axis_ids") or parameters.get("driven_axis_ids")}
    primary_ids=set(axis_ids)
    primary_role_ids={component_id for component_id,roles in role_index.items() if {"support","controlled_motion","moving_surface","moving_body","drive_output","motion_transmission","tool_mount"}&roles}
    for group in connected_groups:
        if (group & actuator_ids and group & moving_ids) or group & axis_ids:
            primary_ids.update(group & primary_role_ids)
    # A disconnected controlled actuator is still a primary-mechanism defect,
    # not a secondary item eligible for independent layout.
    primary_ids.update(actuator_ids)
    # An explicit support with no mechanical relationships is still a valid
    # deterministic assembly root for electronics-only or enclosure projects.
    standalone_supports=sorted(component_id for component_id,roles in role_index.items() if "support" in roles and placement[component_id]=="INDEPENDENT_LAYOUT")
    for support_index,component_id in enumerate(standalone_supports):
        positions[component_id]=[support_index*220.0,0.0,by_id[component_id].dimensions[2]/2]
        placement[component_id]="FIXED_ROOT"
    # Secondary electronics and auxiliary components may use a bounded layout,
    # but that layout is anchored to a real support instead of a remote global
    # subsystem grid.  This does not invent a graph mate or change topology.
    support_ids=sorted((component_id for component_id,roles in role_index.items() if "support" in roles and placement[component_id] in {"FIXED_ROOT","MATE_SOLVED"}),key=lambda item:(placement[item]!="FIXED_ROOT",item))
    independent_mounts={};secondary_index=0
    if support_ids:
        anchor_id=support_ids[0];anchor=by_id[anchor_id]
        secondary_ids=[component_id for component_id in sorted(placement) if component_id not in primary_ids and placement[component_id]=="INDEPENDENT_LAYOUT"]
        cell_width=max((by_id[component_id].dimensions[0] for component_id in secondary_ids),default=45.0)+12.0
        cell_depth=max((by_id[component_id].dimensions[1] for component_id in secondary_ids),default=30.0)+12.0
        host_layout=anchor.family in {"mounting_plate","base","structural_frame"} and any("drive_output" in part.functional_roles for part in parts)
        occupied_right=max((positions[component_id][0]+by_id[component_id].dimensions[0]/2 for component_id in placement if placement[component_id]!="INDEPENDENT_LAYOUT"),default=positions[anchor_id][0]+anchor.dimensions[0]/2)
        for component_id in sorted(placement):
            if component_id in primary_ids or placement[component_id]!="INDEPENDENT_LAYOUT": continue
            part=by_id[component_id];column=secondary_index%3;row=secondary_index//3;secondary_index+=1
            if host_layout:
                columns=min(3,max(1,len(secondary_ids)))
                rows=max(1,(len(secondary_ids)+columns-1)//columns)
                x_step=min(cell_width,max(24.0,(anchor.dimensions[0]-20.0)/columns))
                y_step=min(cell_depth,max(24.0,(anchor.dimensions[1]-16.0)/rows))
                positions[component_id]=[positions[anchor_id][0]+(column-(columns-1)/2)*x_step,positions[anchor_id][1]+(row-(rows-1)/2)*.9*y_step,positions[anchor_id][2]+anchor.dimensions[2]/2+part.dimensions[2]/2]
            else:
                positions[component_id]=[occupied_right+part.dimensions[0]/2+12.0+column*cell_width,positions[anchor_id][1]-anchor.dimensions[1]*.3+row*cell_depth,positions[anchor_id][2]+anchor.dimensions[2]/2+part.dimensions[2]/2]
            placement[component_id]="SEMANTIC_SUPPORT"
            independent_mounts[component_id]=anchor_id
    unresolved_primary=[]
    for component_id in sorted(primary_ids):
        if placement[component_id] in {"INDEPENDENT_LAYOUT","CONCEPTUAL_TOPOLOGY"}:
            unresolved_primary.append({"componentId":component_id,"reason":"primary mechanism lacks a root-to-mate transform"})
    from dataclasses import replace
    parts=[replace(part,assembled=tuple(positions[part.semantic_id]),exploded=tuple(positions[part.semantic_id][i]+(part.exploded[i]-part.assembled[i]) for i in range(3)),rotation=rotations[part.semantic_id],transform_source=placement[part.semantic_id]) for part in parts]
    by_id={part.semantic_id:part for part in parts}
    mechanical_parents={part.semantic_id:[] for part in parts};mechanical_children={part.semantic_id:[] for part in parts}
    mate_diagnostics=[]
    for relationship,constraint in zip(mated,constraints):
        _,source_owner,source,target_owner,target=constraint
        mechanical_children[source_owner].append(target_owner);mechanical_parents[target_owner].append(source_owner)
        source_position=_world_point(by_id[source_owner],source.position);target_position=_world_point(by_id[target_owner],target.position)
        distance=sqrt(sum((a-b)**2 for a,b in zip(source_position,target_position)))
        source_axis=_world_axis(by_id[source_owner],source.axis);target_axis=_world_axis(by_id[target_owner],target.axis)
        alignment=None
        if source_axis and target_axis:
            dot=max(-1.,min(1.,abs(sum(a*b for a,b in zip(source_axis,target_axis)))))
            alignment=degrees(acos(dot))
        mate_diagnostics.append({**relationship,"originDistanceMm":distance,"axisAlignmentDegrees":alignment,
            "originWithinTolerance":distance<=.5,"orientationWithinTolerance":alignment is None or alignment<=1.0})
    part_dicts=[]
    for part in _resolve_exploded_collisions(parts):
        value=part.to_dict();value["mechanicalParents"]=sorted(mechanical_parents[part.semantic_id]);value["mechanicalChildren"]=sorted(mechanical_children[part.semantic_id])
        value["mateInterfaces"]=[item for item in mated if item["from"].startswith(part.semantic_id+":") or item["to"].startswith(part.semantic_id+":")]
        if part.semantic_id in primary_ids or (any(role.startswith("feedback_") for role in part.functional_roles) and mechanical_parents[part.semantic_id]): value["placementClass"]="MATED"
        elif placement[part.semantic_id] in {"FIXED_ROOT","MATE_SOLVED"} or part.semantic_id in independent_mounts: value["placementClass"]="MOUNTED_INDEPENDENTLY"
        elif placement[part.semantic_id]=="CONCEPTUAL_TOPOLOGY": value["placementClass"]="CONCEPTUAL_FREE"
        else: value["placementClass"]="UNRESOLVED"
        half=[dimension/2 for dimension in part.dimensions];value["representationBounds"]={"min":[part.assembled[i]-half[i] for i in range(3)],"max":[part.assembled[i]+half[i] for i in range(3)]}
        value["independentMountAnchor"]=independent_mounts.get(part.semantic_id)
        value["mountSource"]=(f"semantic_support:{independent_mounts[part.semantic_id]}" if part.semantic_id in independent_mounts
            else "graph_mate" if placement[part.semantic_id] in {"FIXED_ROOT","MATE_SOLVED"}
            else "unresolved")
        part_dicts.append(value)
    world_interfaces=[]
    for item in interfaces:
        owner=by_id[item["semanticId"]];world=dict(item);world["worldPosition"]=list(_world_point(owner,tuple(item["localPosition"])))
        world["worldAxis"]=list(_world_axis(owner,tuple(item["axis"]))) if item.get("axis") else None;world_interfaces.append(world)
    # Harness geometry is a projection of graph-owned nets. Routes terminate
    # at interface frames, never at arbitrary component centres.
    interface_positions={item["interfaceId"]:item["worldPosition"] for item in world_interfaces}
    wires=[]
    for net in electrical_nets(graph):
        terminals=[]
        for terminal in net.get("terminals",[]):
            interface_id=f"{terminal['componentId']}:{terminal['interfaceId']}"
            position=interface_positions.get(interface_id)
            if position is not None:
                terminals.append({**terminal,"interfaceId":interface_id,"worldPosition":position})
        if len(terminals)<2: continue
        terminals.sort(key=lambda item:item["interfaceId"])
        clearance_z=max(item["worldPosition"][2] for item in terminals)+12.0
        bus=[sum(item["worldPosition"][0] for item in terminals)/len(terminals),
             sum(item["worldPosition"][1] for item in terminals)/len(terminals),clearance_z]
        route_indices=range(1) if len(terminals)==2 else range(len(terminals))
        for index in route_indices:
            terminal=terminals[index];start=list(terminal["worldPosition"]);exit_point=[start[0],start[1],clearance_z]
            if len(terminals)==2:
                other=terminals[1]["worldPosition"]
                points=[start,exit_point,[other[0],start[1],clearance_z],[other[0],other[1],clearance_z],list(other)]
            else:
                points=[start,exit_point,[bus[0],start[1],clearance_z],bus]
            compact=[]
            for point in points:
                if not compact or point!=compact[-1]: compact.append(point)
            role=str(net.get("role","signal"))
            wires.append({"wireId":f"wire-{net['netId']}-{index+1}","netId":net["netId"],"role":role,
                "color":net.get("displayStyle",{}).get("color","#81e6d9"),"thicknessClass":"power" if "power" in role else "signal",
                "thicknessMm":2.2 if "power" in role else 1.4,"terminalInterfaceIds":[item["interfaceId"] for item in terminals],
                "points":compact,"source":"ENGINEERING_GRAPH_NET"})
    severe_intersections=[]
    mated_pairs={frozenset((item["from"].rsplit(":",1)[0],item["to"].rsplit(":",1)[0])) for item in mated}
    for index,left in enumerate(parts):
        for right in parts[index+1:]:
            if frozenset((left.semantic_id,right.semantic_id)) in mated_pairs: continue
            ratio=_overlap_ratio(left,right)
            if ratio>=.8: severe_intersections.append({"a":left.semantic_id,"b":right.semantic_id,"smallerVolumeOverlap":ratio})
    sources=("MATE_SOLVED","FIXED_ROOT","SEMANTIC_SUPPORT","INDEPENDENT_LAYOUT","CONCEPTUAL_TOPOLOGY","FALLBACK")
    source_counts={source:sum(part.transform_source==source for part in parts) for source in sources}
    physical_limitations=[{"componentId":part["semanticId"],"reason":"physical component lacks a resolved structural placement"} for part in part_dicts if part["placementClass"] in {"CONCEPTUAL_FREE","UNRESOLVED"}]
    return {"assemblyId":f"assembly-{graph.project_id}","units":"mm","coordinateSystem":{"forward":"+X","left":"+Y","up":"+Z"},"hierarchy":hierarchy,"parts":part_dicts,"interfaces":world_interfaces,"connectors":world_interfaces,"wires":wires,"wireCount":len(wires),"relationships":mated,"mateDiagnostics":mate_diagnostics,"visualizationPose":visualization_pose,"visualConnectivity":{"allMateOriginsWithinTolerance":all(item["originWithinTolerance"] for item in mate_diagnostics),"allMateAxesWithinTolerance":all(item["orientationWithinTolerance"] for item in mate_diagnostics),"severeIntersections":severe_intersections},"physicalRepresentationLimitations":physical_limitations,"unresolvedMechanicalRelations":unresolved,"primaryMechanismIds":sorted(primary_ids),"unresolvedPrimaryMechanism":unresolved_primary,"transformSourceCounts":source_counts,"revision":len(graph.revisions),"layoutStatus":"conceptual mechanical assembly","placementMethod":"interface-frame-mating"}

def _world_point(part:PhysicalPart,local:tuple[float,float,float])->tuple[float,float,float]:
    rotated=_rotate(part.rotation,local);return tuple(part.assembled[i]+rotated[i] for i in range(3))

def _world_axis(part:PhysicalPart,axis:tuple[float,float,float]|None)->tuple[float,float,float]|None:
    if not axis:return None
    rotated=_rotate(part.rotation,axis);length=max(sqrt(sum(value*value for value in rotated)),1e-9);return tuple(value/length for value in rotated)

def _overlap_ratio(left:PhysicalPart,right:PhysicalPart)->float:
    overlap=1.
    for a,b,ad,bd in zip(left.assembled,right.assembled,left.dimensions,right.dimensions):
        overlap*=max(0.,min(a+ad/2,b+bd/2)-max(a-ad/2,b-bd/2))
    smaller=min(_volume(left.dimensions),_volume(right.dimensions));return overlap/max(smaller,1e-9)

def _volume(dimensions:tuple[float,float,float])->float:return dimensions[0]*dimensions[1]*dimensions[2]

def _representation_features(family:str)->tuple[str,...]:
    features={
        "servo":("body","mounting_ears","output_shaft","cross_horn","cable_exit"),
        "microcontroller_board":("pcb","usb_connector","header_rows","module_blocks"),
        "controller":("pcb","connector","header_rows","module_blocks"),
        "small_dc_motor":("motor_body","output_shaft","rear_cap"),
        "drive_wheel":("rounded_tire","sidewall","rim","spokes","hub","axle_bore","bounded_tread"),
        "light_sensor":("sensor_pcb","four_quadrant_head","divider_cross"),
        "temperature_sensor":("sensor_pcb","sensing_element","header"),
        "environmental_sensor":("sensor_pcb","sensing_element","header"),
        "distance_sensor":("sensor_pcb","ranging_head","header"),
        "conceptual_sensor":("sensor_pcb","conceptual_sensing_head","header"),
        "panel":("thin_surface","backing_frame","rear_mount","cell_grid"),
        "articulated_link":("beam","proximal_joint","distal_joint"),
        "rotating_platform":("platform","hub","mounting_surface"),
        "camera_platform":("platform","hub","camera_body","lens_cue"),
        "tool_platform":("platform","hub","tool_mount"),
        "linear_drive":("drive_body","lead_screw","carriage"),
        "sliding_panel":("moving_panel","guide_rollers"),
        "low_voltage_power_source":("battery_pack","terminals","cell_cues"),
        "base":("base_plate","central_mount","fasteners"),
        "mounting_plate":("base_plate","mounting_face","fasteners"),
        "structural_frame":("stationary_frame","side_rails","top_rail","mounting_face"),
    }
    return features.get(family,("family_aware_body",))

def _representation_parameters(family:str,dimensions:tuple[float,float,float])->dict[str,float]:
    if family!="drive_wheel":return {}
    diameter=max(dimensions[0],dimensions[1]);width=max(8.0,dimensions[2])
    return {"outerDiameter":diameter,"tireWidth":width,"rimDiameter":diameter*.58,
        "hubDiameter":diameter*.21,"axleBore":diameter*.08,"treadDepth":max(1.4,diameter*.026)}

def _axis_angle(axis:tuple[float,float,float],angle:float)->tuple[float,float,float,float]:
    length=max(sqrt(sum(value*value for value in axis)),1e-9);scale=sin(angle/2)/length
    return (axis[0]*scale,axis[1]*scale,axis[2]*scale,cos(angle/2))

def _quat_multiply(left:tuple[float,float,float,float],right:tuple[float,float,float,float])->tuple[float,float,float,float]:
    ax,ay,az,aw=left;bx,by,bz,bw=right
    return (aw*bx+ax*bw+ay*bz-az*by,aw*by-ax*bz+ay*bw+az*bx,aw*bz+ax*by-ay*bx+az*bw,aw*bw-ax*bx-ay*by-az*bz)

def _resolve_exploded_collisions(parts: list[PhysicalPart]) -> list[PhysicalPart]:
    """Deterministically extend withdrawal vectors until exploded AABBs clear."""
    from dataclasses import replace
    resolved: list[PhysicalPart]=[]
    for part in parts:
        position=list(part.exploded)
        direction=[b-a for a,b in zip(part.assembled,part.exploded)]
        for _ in range(8):
            if not any(_aabb_overlap(position,part.dimensions,list(other.exploded),other.dimensions) for other in resolved): break
            length=max(sum(value*value for value in direction)**.5,1.0)
            position=[value+axis/length*20 for value,axis in zip(position,direction)]
        resolved.append(replace(part,exploded=tuple(position)))
    return resolved


def _aabb_overlap(a:list[float],ad:tuple[float,float,float],b:list[float],bd:tuple[float,float,float])->bool:
    return all(abs(x-y)<(dx+dy)/2+8 for x,y,dx,dy in zip(a,b,ad,bd))


def _rotate(q:tuple[float,float,float,float], vector:tuple[float,float,float])->tuple[float,float,float]:
    x,y,z,w=q;vx,vy,vz=vector
    tx,ty,tz=2*(y*vz-z*vy),2*(z*vx-x*vz),2*(x*vy-y*vx)
    return (vx+w*tx+y*tz-z*ty,vy+w*ty+z*tx-x*tz,vz+w*tz+x*ty-y*tx)


def _from_to(source:tuple[float,float,float],target:tuple[float,float,float])->tuple[float,float,float,float]:
    sl=max(sqrt(sum(value*value for value in source)),1e-9);tl=max(sqrt(sum(value*value for value in target)),1e-9)
    a=tuple(value/sl for value in source);b=tuple(value/tl for value in target);dot=sum(x*y for x,y in zip(a,b))
    if dot>0.999999:return (0.,0.,0.,1.)
    if dot<-.999999:
        axis=(1.,0.,0.) if abs(a[0])<.9 else (0.,1.,0.)
        cross=(a[1]*axis[2]-a[2]*axis[1],a[2]*axis[0]-a[0]*axis[2],a[0]*axis[1]-a[1]*axis[0]);length=sqrt(sum(value*value for value in cross))
        return tuple(value/length for value in cross)+(0.,)
    cross=(a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]);scale=sqrt((1+dot)*2)
    return (cross[0]/scale,cross[1]/scale,cross[2]/scale,scale/2)


def interpolate_position(part: dict[str, Any], amount: float, subsystem: str | None = None) -> tuple[float,float,float]:
    amount=max(0.0,min(1.0,amount))
    if subsystem and part["subsystem"] != subsystem: amount=0.0
    assembled=part["assembledTransform"]["position"]; exploded=part["explodedTransform"]["position"]
    return tuple(a+(b-a)*amount for a,b in zip(assembled,exploded))
