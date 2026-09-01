from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .evidence import EvidenceKind, EvidenceRecord
from .units import in_range

CATALOGUE_VERSION = "catalogue-v1"


@dataclass(frozen=True)
class PropertyFact:
    value: Any
    unit: str | None
    evidence_id: str
    qualifier: str = "rated"

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "unit": self.unit, "evidenceId": self.evidence_id,
                "qualifier": self.qualifier}


@dataclass(frozen=True)
class ComponentDefinition:
    component_definition_id: str
    family: str
    manufacturer: str
    part_number: str
    properties: dict[str, PropertyFact]
    interfaces: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    representation: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"componentDefinitionId": self.component_definition_id, "componentDefinitionVersion": CATALOGUE_VERSION, "family": self.family,
                "manufacturer": self.manufacturer, "partNumber": self.part_number,
                "properties": {k: v.to_dict() for k, v in self.properties.items()},
                "interfaces": list(self.interfaces), "evidenceIds": list(self.evidence_ids),
                "representation": self.representation}


_SOURCES = {
    "espressif": EvidenceRecord.curated("evidence-espressif-esp32", EvidenceKind.MANUFACTURER_DATASHEET,
        "ESP32 Series Datasheet", "https://www.espressif.com/sites/default/files/documentation/esp32_datasheet_en.pdf", "Espressif Systems", ("supply_voltage", "logic_voltage", "gpio_current"), "ESP32 datasheet"),
    "bosch": EvidenceRecord.curated("evidence-bosch-bme280", EvidenceKind.MANUFACTURER_DATASHEET,
        "BME280 Combined Humidity and Pressure Sensor", "https://www.bosch-sensortec.com/products/environmental-sensors/humidity-sensors-bme280/", "Bosch Sensortec", ("supply_voltage", "current"), "BME280"),
    "ti": EvidenceRecord.curated("evidence-ti-drivers", EvidenceKind.MANUFACTURER_DATASHEET,
        "Low-voltage motor and load driver technical documentation", "https://www.ti.com/motor-drivers/overview.html", "Texas Instruments", ("supply_voltage", "logic_voltage", "current")),
    "st": EvidenceRecord.curated("evidence-st-protection", EvidenceKind.MANUFACTURER_DATASHEET,
        "Discrete protection device documentation", "https://www.st.com/en/diodes-and-rectifiers.html", "STMicroelectronics", ("current", "reverse_voltage")),
    "adafruit": EvidenceRecord.curated("evidence-adafruit-modules", EvidenceKind.MANUFACTURER_PRODUCT_PAGE,
        "Low-voltage hobby module technical specifications", "https://www.adafruit.com/category/35", "Adafruit Industries", ("supply_voltage", "current", "dimensions")),
    "assumption": EvidenceRecord.curated("evidence-curated-component-assumptions", EvidenceKind.ENGINEERING_ASSUMPTION,
        "AURA bounded component-family assumptions", "aura://curated-assumptions/v1", "AURA", ("supply_voltage", "current", "dimensions"), "v1"),
    "dfrobot": EvidenceRecord.curated("evidence-dfrobot-sen0193", EvidenceKind.MANUFACTURER_PRODUCT_PAGE,
        "Capacitive Soil Moisture Sensor SEN0193", "https://wiki.dfrobot.com/Capacitive_Soil_Moisture_Sensor_SKU_SEN0193", "DFRobot", ("supply_voltage", "dimensions"), "SEN0193"),
    "stmicro-vl53": EvidenceRecord.curated("evidence-st-vl53l0x", EvidenceKind.MANUFACTURER_PRODUCT_PAGE,
        "VL53L0X time-of-flight ranging sensor", "https://www.st.com/en/imaging-and-photonics-solutions/vl53l0x.html", "STMicroelectronics", ("supply_voltage", "current", "dimensions"), "VL53L0X"),
    "arduino": EvidenceRecord.curated("evidence-arduino-uno", EvidenceKind.MANUFACTURER_PRODUCT_PAGE,
        "Arduino UNO R4 Minima technical specifications", "https://docs.arduino.cc/hardware/uno-r4-minima/", "Arduino", ("supply_voltage", "logic_voltage", "dimensions"), "UNO R4 Minima"),
}


def _p(value: Any, unit: str | None, evidence: str, qualifier: str = "rated") -> PropertyFact:
    return PropertyFact(value, unit, _SOURCES[evidence].evidence_id, qualifier)


def _definition(identifier: str, family: str, manufacturer: str, part: str, source: str,
                voltage=(3.0, 3.6), current_ma: float | None = None,
                dimensions: tuple[float, float, float] | None = None,
                interfaces: tuple[str, ...] = ("power", "ground", "signal")) -> ComponentDefinition:
    props = {"supply_voltage_range": _p(list(voltage), "V", source)}
    if current_ma is not None: props["current"] = _p(current_ma, "mA", source, "maximum")
    if dimensions is not None: props["dimensions"] = _p(list(dimensions), "mm", source)
    evidence = _SOURCES[source].evidence_id
    return ComponentDefinition(identifier, family, manufacturer, part, props, interfaces, (evidence,),
                               {"type": "proxy", "dimensionsProperty": "dimensions"})


# Deliberately small, reviewable catalogue: variants cover the six supported benchmark families.
_SPECS = (
 ("arduino-nano-v3","microcontroller_board","Arduino-compatible","Arduino Nano V3","assumption",(4.5,12),200,(45,18,8)),
 ("esp32-devkit-v1","microcontroller_board","Espressif","ESP32-DevKitC","espressif",(4.75,5.25),240,(28,52,12)),
 ("esp8266-nodemcu-v3","microcontroller_board","Espressif-compatible","NodeMCU ESP8266","assumption",(4.5,5.5),500,(31,58,13)),
 ("raspberry-pi-pico","microcontroller_board","Raspberry Pi","Pico","assumption",(1.8,5.5),300,(51,21,4)),
 ("esp32-wroom-32e","microcontroller_board","Espressif","ESP32-WROOM-32E","espressif",(3.0,3.6),240,(18,25.5,3.1)),
 ("arduino-uno-r4","microcontroller_board","Arduino","UNO R4 Minima","arduino",(6,24),200,(68.85,53.34,15)),
 ("bme280-breakout","environmental_sensor","Bosch","BME280","bosch",(1.71,3.6),1.0,(10,10,3)),
 ("bme280-i2c-module","temperature_sensor","Bosch","BME280 module","bosch",(3.0,5.0),1.0,(15,12,3)),
 ("dht11-module","temperature_sensor","Curated","DHT11 module","assumption",(3.0,5.5),2.5,(28,15,8)),
 ("dht22-module","temperature_sensor","Curated","DHT22 module","assumption",(3.0,5.5),2.5,(28,15,10)),
 ("lm35-module","temperature_sensor","Curated","LM35 module","assumption",(4.0,30),1.0,(20,15,6)),
 ("aht20-module","temperature_sensor","Adafruit","AHT20 breakout","adafruit",(2.7,5.5),1.0,(25.5,17.8,4.6)),
 ("vl53l0x-module","distance_sensor","STMicroelectronics","VL53L0X","stmicro-vl53",(2.6,3.5),20,(4.4,2.4,1)),
 ("hc-sr04-class","distance_sensor","Curated","HC-SR04 class","assumption",(4.5,5.5),15,(45,20,15)),
 ("capacitive-soil-v1","soil_moisture_sensor","DFRobot","SEN0193","dfrobot",(3.3,5.5),5,(98,23,4)),
 ("photoresistor-module","light_sensor","Curated","CdS module","assumption",(3.0,5.0),5,(32,14,7)),
 ("bh1750-module","light_sensor","Curated","BH1750 module","assumption",(3.0,5.0),1,(18,13,4)),
 ("pir-hc-sr501","motion_sensor","Curated","HC-SR501 PIR","assumption",(4.5,12),65,(32,24,24)),
 ("mpu6050-module","orientation_sensor","Curated","MPU6050 module","assumption",(3.0,5.0),4,(21,16,4)),
 ("micro-pump-5v","small_dc_pump","Curated","5 V micro pump","assumption",(4.5,5.5),800,(60,40,35)),
 ("micro-pump-12v","small_dc_pump","Curated","12 V micro pump","assumption",(9,12),500,(60,40,35)),
 ("dc-fan-5v","fan","Curated","5 V brushless fan","assumption",(4.5,5.5),300,(40,40,10)),
 ("dc-fan-12v","fan","Curated","12 V brushless fan","assumption",(10.8,13.2),250,(60,60,15)),
 ("dc-motor-6v","small_dc_motor","Curated","DC toy motor","assumption",(3,6),500,(25,20,15)),
 ("sg90-servo","servo","Curated","SG90 class","assumption",(4.8,6),650,(23,12,29)),
 ("mg996r-servo","servo","Curated","MG996R class","assumption",(4.8,7.2),2500,(41,20,43)),
 ("drv8833-module","motor_driver","Texas Instruments","DRV8833 module","ti",(2.7,10.8),1500,(25,20,5)),
 ("tb6612-module","motor_driver","Toshiba","TB6612FNG module","adafruit",(2.7,5.5),1200,(25,20,5)),
 ("l298n-module","motor_driver","ST-compatible","L298N module","assumption",(5,35),2000,(44,44,28)),
 ("uln2003-module","motor_driver","Texas Instruments-compatible","ULN2003 module","assumption",(3,5.5),500,(32,24,8)),
 ("logic-mosfet-module","mosfet_driver","Curated","Logic MOSFET module","assumption",(3.3,5),10000,(34,26,12)),
 ("relay-module-5v","relay_module","Curated","5 V relay module","assumption",(4.5,5.5),80,(50,26,18)),
 ("bare-relay-5v","relay_module","Curated","5 V bare relay","assumption",(4.5,5.5),80,(20,15,15)),
 ("npn-switch","mosfet_driver","Curated","NPN transistor switch","assumption",(3.0,12),500,(10,5,10)),
 ("1n4007-diode","flyback_diode","STMicroelectronics","1N4007","st",(0,1000),1000,(10,3,3)),
 ("ss14-diode","flyback_diode","STMicroelectronics","SS14","st",(0,40),1000,(5,3,2)),
 ("resistor-220r","resistor","IEC family","220 ohm resistor","st",(0,250),0.25,(6.5,2.5,2.5)),
 ("resistor-1k","resistor","IEC family","1 kohm resistor","st",(0,250),0.25,(6.5,2.5,2.5)),
 ("resistor-10k","resistor","IEC family","10 kohm resistor","st",(0,250),0.25,(6.5,2.5,2.5)),
 ("capacitor-generic","capacitor","IEC family","Generic capacitor","assumption",(0,50),1,(6,6,10)),
 ("led-generic","indicator","IEC family","Low-current LED","assumption",(1.8,3.3),20,(5,5,8)),
 ("push-button","switch","IEC family","Momentary push button","assumption",(0,24),100,(12,12,8)),
 ("terminal-block-2p","terminal_block","Curated","Two-position terminal block","assumption",(0,50),10000,(10,8,10)),
 ("supply-usb-5v-1a","low_voltage_power_source","Curated","5 V 1 A supply","assumption",(4.75,5.25),1000,(45,35,25)),
 ("supply-usb-5v-2a","low_voltage_power_source","Curated","5 V 2 A supply","assumption",(4.75,5.25),2000,(45,35,25)),
 ("supply-dc-12v-2a","low_voltage_power_source","Curated","12 V 2 A supply","assumption",(11.4,12.6),2000,(80,45,30)),
 ("buck-5v-3a","buck_converter","Texas Instruments","5 V buck module","ti",(7,24),3000,(43,21,14)),
 ("battery-aa4","battery","Curated","4xAA holder","assumption",(4,6.4),2000,(58,32,16)),
 ("enclosure-100x120","enclosure","Curated","Splash-resistant 100x120","assumption",(0,1),0,(100,120,60)),
 ("enclosure-160x200","enclosure","Curated","Splash-resistant 160x200","assumption",(0,1),0,(160,200,80)),
)

CATALOGUE = tuple(_definition(*spec) for spec in _SPECS)
BY_ID = {item.component_definition_id: item for item in CATALOGUE}


def evidence_records() -> tuple[EvidenceRecord, ...]: return tuple(_SOURCES.values())
def get(component_definition_id: str) -> ComponentDefinition:
    try: return BY_ID[component_definition_id]
    except KeyError as exc: raise KeyError(f"Unknown curated component: {component_definition_id}") from exc
def search(*, family: str | None = None, voltage: float | None = None, voltage_unit: str = "V",
           minimum_current_ma: float | None = None, interface: str | None = None) -> list[ComponentDefinition]:
    result=[]
    for item in CATALOGUE:
        if family and item.family != family: continue
        vr=item.properties.get("supply_voltage_range")
        if voltage is not None and (not vr or not in_range(voltage,voltage_unit,*vr.value,vr.unit or "V")): continue
        current=item.properties.get("current")
        if minimum_current_ma is not None and (not current or float(current.value)<minimum_current_ma): continue
        if interface and interface not in item.interfaces: continue
        result.append(item)
    return result
