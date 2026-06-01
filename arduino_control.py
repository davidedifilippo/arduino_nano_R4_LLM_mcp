import sys
import time
import logging
import json
import subprocess
from typing import List, Optional, Dict, Any
import serial
from serial.tools import list_ports
from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
import mcp.types as types
import mcp.server.stdio

# Logging configuration
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", stream=sys.stderr)
logger = logging.getLogger("mcp_arduino_server")

BAUD_RATE = 9600


def get_arduino_boards_cli():
    """Ottiene la lista delle board usando arduino-cli"""
    try:
        result = subprocess.run(
            ['arduino-cli', 'board', 'list', '--format', 'json'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        else:
            logger.error(f"arduino-cli error: {result.stderr}")
            return {}
    except Exception as e:
        logger.error(f"Failed to run arduino-cli: {e}")
        return {}


def find_arduino_port():
    """Trova la porta dell'Arduino usando arduino-cli"""
    boards = get_arduino_boards_cli()
    
    if not boards or 'detected_ports' not in boards:
        logger.error("No ports detected by arduino-cli")
        return None, None
    
    detected_ports = boards.get('detected_ports', [])
    
    logger.info(f"Found {len(detected_ports)} port(s) via arduino-cli")
    
    # Cerca la prima porta con una board Arduino riconosciuta
    for item in detected_ports:
        matching_boards = item.get('matching_boards', [])
        if matching_boards:
            port = item.get('port', {})
            board = matching_boards[0]
            address = port.get('address')
            fqbn = board.get('fqbn')
            logger.info(f"Found Arduino board on {address}: {board.get('name', 'Unknown')} ({fqbn})")
            return address, fqbn
    
    # Se non trova nulla di riconosciuto, torna la prima porta usbmodem
    for item in detected_ports:
        port = item.get('port', {})
        address = port.get('address', '')
        if 'usbmodem' in address:
            logger.info(f"Found usbmodem port: {address}")
            return address, None
    
    return None, None


class ArduinoManager:
    def __init__(self):
        self.serial_conn: Optional[serial.Serial] = None
        self.port: Optional[str] = None
        self.board_info: Dict[str, str] = {
            "mcu": "Unknown",
            "fqbn": "Unknown",
            "port": "None"
        }
        self.device_map: Dict[str, Dict[str, Any]] = {}
        self.pin_map: Dict[str, str] = {}
        
    def _read_response(self, expected_cmd: str = "") -> str:
        """Legge la risposta reale dalla seriale ignorando l'eco del comando."""
        deadline = time.time() + 3
        while time.time() < deadline:
            try:
                if self.serial_conn.in_waiting:
                    line = self.serial_conn.readline().decode(errors='replace').strip()
                    if not line:
                        continue
                    if line == expected_cmd:
                        continue
                    return line
            except Exception as e:
                logger.warning(f"Read error: {e}")
            time.sleep(0.1)
        return ""

    def connect(self) -> bool:
        """Connette all'Arduino usando arduino-cli per trovare la porta"""
        if self.serial_conn:
            return True

        # Trova la porta usando arduino-cli
        logger.info("Searching for Arduino board using arduino-cli...")
        port, fqbn = find_arduino_port()
        
        if not port:
            logger.error("No Arduino board found!")
            return False
        
        try:
            logger.info(f"Opening serial connection on {port} at {BAUD_RATE} baud...")
            test_serial = serial.Serial(port=port, baudrate=BAUD_RATE, timeout=2)
            time.sleep(3) # Aumentato a 3 secondi per Nano R4
            
            # Pulisce il buffer da eventuali residui di boot
            test_serial.reset_input_buffer()
            
            logger.info("Sending IDENT command...")
            test_serial.write(b"IDENT\n")
            self.serial_conn = test_serial 
            line = self._read_response(expected_cmd="IDENT")
            logger.info(f"Response for IDENT: '{line}'")
            
            if line.startswith("ID:"):
                parts = line[3:].split("|")
                self.board_info["mcu"] = parts[0] if len(parts) > 0 else "Unknown"
                self.board_info["fqbn"] = parts[1] if len(parts) > 1 else (fqbn if fqbn else "Unknown")
                self.board_info["port"] = port
                self.port = port
                self._load_standard_pin_map()
                self._auto_discover_mapping()
                logger.info(f"Connected to {self.board_info['fqbn']} on {self.port}")
                return True
            else:
                logger.error(f"Unexpected response: {line}")
                self.serial_conn = None
                test_serial.close()
                return False
                
        except Exception as e:
            logger.error(f"Failed to connect to {port}: {e}")
            self.serial_conn = None
            return False

    def _auto_discover_mapping(self):
        """Asks the Arduino for its pre-configured device map."""
        res = self.send_command("MAP")
        if res.startswith("MAP:"):
            mappings = res[4:].split(",")
            for m in mappings:
                if "=" in m:
                    dev_name, pin = m.split("=")
                    dev_name = dev_name.strip()
                    pin = pin.strip()
                    dev_type = self._infer_device_type(dev_name, pin)

                    self.device_map[dev_name] = {
                        "pin": pin,
                        "device_name": dev_name,
                        "type": dev_type,
                        "description": "Auto-discovered via MAP command"
                    }
            logger.info(f"Auto-discovered {len(self.device_map)} devices")

    def _infer_device_type(self, dev_name: str, pin: str) -> str:
        name = dev_name.upper()
        pin_key = pin.upper()

        if "DAC" in name or pin_key == "DAC" or name == "A0":
            return "dac"
        if "LED" in name:
            return "output"
        if "MOTOR" in name or "PWM" in name or (pin_key.isdigit() and int(pin_key) in {3, 5, 6, 9, 10, 11}):
            return "pwm"
        if "TMP102" in pin_key or "TEMP" in name or "SENSOR" in name or name == "I2C":
            return "sensor"
        return "output"

    def _sensor_command(self, pin: str) -> str:
        if pin.upper() in {"TMP102", "I2C"}:
            return "AR:I2C"
        return f"AR:{pin}"

    def _load_standard_pin_map(self):
        fqbn = self.board_info.get("fqbn", "unknown").lower()
        # Default map (Classic Uno)
        base_map = {
            "0": "RX", "1": "TX", "2": "D2", "3": "D3 (PWM)", "4": "D4", 
            "5": "D5 (PWM)", "6": "D6 (PWM)", "7": "D7", "8": "D8", 
            "9": "D9 (PWM)", "10": "D10 (PWM/SS)", "11": "D11 (PWM/MOSI)", 
            "12": "D12 (MISO)", "13": "D13 (SCK/LED)", "A0": "A0 (DAC)", 
            "A1": "A1", "A2": "A2", "A3": "A3", "A4": "A4 (SDA)", "A5": "A5 (SCL)"
        }
        
        if "nano" in fqbn and "r4" in fqbn:
            # Nano R4 specific mapping
            base_map.update({
                "A6": "A6",
                "A7": "A7",
                "LEDR": "Onboard Red LED (PWM)",
                "LEDG": "Onboard Green LED (PWM)",
                "LEDB": "Onboard Blue LED (PWM)",
                "I2C": "I2C Bus / TMP102"
            })
        elif "uno" in fqbn and "r4" in fqbn:
            base_map.update({"A0": "A0 (DAC)"})
            
        self.pin_map = base_map

    def send_command(self, cmd: str) -> str:
        if not self.serial_conn:
            return "Error: Not connected"
        try:
            self.serial_conn.write(f"{cmd}\n".encode())
            if cmd:
                return self._read_response(expected_cmd=cmd)
            return self._read_response()
        except Exception as e:
            return f"Error: {e}"

manager = ArduinoManager()
server = Server("arduino-advanced-control")

@server.list_tools()
async def handle_list_tools() -> List[types.Tool]:
    return [
        types.Tool(
            name="get_board_info",
            description="Restituisce info su MCU, porta e FQBN della board.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="get_device_mapping",
            description="Mostra i dispositivi di ingresso/uscita attualmente mappati sulla scheda Nano R4.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="get_pin_map",
            description="Restituisce la mappa dei pin standard supportati dal firmware Nano R4.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="set_device_mapping",
            description="Mappa un nome logico a un pin fisico e definisce il tipo di dispositivo.",
            inputSchema={
                "type": "object",
                "properties": {
                    "device_name": {"type": "string", "description": "Esempi: 'LED Rosso', 'Sensore Temp', 'Motore', 'TMP102'"},
                    "pin": {"type": "string", "description": "Esempi: '13', 'A0', 'LEDR', 'I2C'"},
                    "type": {"type": "string", "enum": ["output", "pwm", "sensor", "dac"]}
                },
                "required": ["device_name", "pin", "type"]
            }
        ),
        types.Tool(
            name="get_system_status",
            description="Legge lo stato di tutti i dispositivi mappati, incluso il sensore TMP102 se presente.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="control_actuator",
            description="Imposta il valore di un'uscita (Digital, PWM o DAC).",
            inputSchema={
                "type": "object",
                "properties": {
                    "device_name": {"type": "string"},
                    "value": {"type": "string", "description": "ON/OFF, 0-255, 0-100%, o voltaggio (es. '2.3V')"}
                },
                "required": ["device_name", "value"]
            }
        ),
        types.Tool(
            name="read_sensor_data",
            description="Legge i dati da un sensore specifico, incluso TMP102/I2C.",
            inputSchema={"type": "object", "properties": {"device_name": {"type": "string"}}, "required": ["device_name"]}
        ),
        types.Tool(
            name="read_tmp102",
            description="Legge la temperatura dal sensore TMP102 collegato alla bus I2C.",
            inputSchema={"type": "object", "properties": {}}
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> List[types.TextContent]:
    if not manager.serial_conn:
        if not manager.connect():
             return [types.TextContent(type="text", text="Errore: Impossibile connettersi all'Arduino. Verificare il collegamento.")]

    try:
        if name == "get_board_info":
            return [types.TextContent(type="text", text=json.dumps(manager.board_info, indent=2))]

        elif name == "get_device_mapping":
            return [types.TextContent(type="text", text=json.dumps(manager.device_map, indent=2))]

        elif name == "get_pin_map":
            return [types.TextContent(type="text", text=json.dumps(manager.pin_map, indent=2))]

        elif name == "set_device_mapping":
            dev_name = arguments["device_name"]
            pin = arguments["pin"]
            dev_type = arguments["type"]
            manager.device_map[dev_name] = {
                "pin": pin,
                "device_name": dev_name,
                "type": dev_type,
                "description": "Manually mapped via tool"
            }
            return [types.TextContent(type="text", text=f"Mappato correttamente: {dev_name} su pin {pin} ({dev_type})")]

        elif name == "get_system_status":
            results = {}
            for dev_name, info in manager.device_map.items():
                pin = info["pin"]
                if info["type"] == "sensor":
                    results[dev_name] = manager.send_command(manager._sensor_command(pin))
                elif info["type"] in ["output", "pwm", "dac"]:
                    results[dev_name] = "Disponibile (Uscita)"
            return [types.TextContent(type="text", text=json.dumps(results, indent=2))]

        elif name == "control_actuator":
            dev_name = arguments["device_name"]
            val = arguments["value"]
            if dev_name not in manager.device_map:
                return [types.TextContent(type="text", text=f"Errore: Dispositivo '{dev_name}' non trovato.")]
            
            info = manager.device_map[dev_name]
            pin = info["pin"]
            
            if info["type"] == "output":
                cmd = f"DW:{pin}:{'1' if val.upper() == 'ON' else '0'}"
            elif info["type"] == "pwm":
                if "%" in val:
                    raw = int(float(val.replace("%","")) * 2.55)
                    cmd = f"AW:{pin}:{raw}"
                else:
                    cmd = f"AW:{pin}:{val}"
            elif info["type"] == "dac":
                cmd = f"DAC:{pin}:{val}"
            else:
                return [types.TextContent(type="text", text="Tipo non supportato.")]
            
            res = manager.send_command(cmd)
            return [types.TextContent(type="text", text=f"Risposta: {res}")]

        elif name == "read_sensor_data":
            dev_name = arguments["device_name"]
            info = manager.device_map.get(dev_name)
            if not info: return [types.TextContent(type="text", text="Dispositivo non trovato.")]
            res = manager.send_command(manager._sensor_command(info['pin']))
            return [types.TextContent(type="text", text=f"{dev_name}: {res}")]

        elif name == "read_tmp102":
            res = manager.send_command("AR:I2C")
            return [types.TextContent(type="text", text=f"TMP102 Temperature: {res}")]

    except Exception as e:
        return [types.TextContent(type="text", text=f"Errore: {str(e)}")]

    return [types.TextContent(type="text", text="Tool non trovato.")]

async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        logger.info("il server è pronto")
        await server.run(read_stream, write_stream, InitializationOptions(
            server_name="arduino-advanced-control",
            server_version="0.3.0",
            capabilities=server.get_capabilities(notification_options=NotificationOptions(), experimental_capabilities={}),
        ))

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
