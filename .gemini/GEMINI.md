# MCP for Arduino Board (Advanced Control)

A Python project that implements an advanced MCP (Model Context Protocol) server to interface LLMs with Arduino boards.

## Project Overview

- **Purpose**: Enables LLMs to discover the board, map pins and devices, and perform telemetry/control on Arduino Nano R4 hardware.
- **Main Technologies**: Python 3.13+, mcp SDK, pyserial, uv.
- **Architecture**:
  - `arduino_control.py`: Advanced MCP server con mapping stateful dei dispositivi e identificazione board per Arduino Nano R4.
  - Supporta la scoperta automatica di schede Nano R4 e la mappatura firmware-specifica dei dispositivi.

## Core Features

1.  **Board Discovery**: Automatically identifies MCU, Port, and FQBN.
2.  **Pin Mapping**: Dynamic retrieval of standard pinouts for the detected board.
3.  **Device Mapping**: Allows the LLM to map specific pins to logical devices (e.g., "pin 2" -> "Blue LED").
4.  **Telemetry**: Read digital inputs, analog sensors (AR), and I2C devices.
5.  **Actuation**: Control digital outputs, PWM duty cycles (0-100%), and DAC voltages.

## Building and Running

### Prerequisites
- Python 3.13+ and uv.
- Arduino board with the **arduino_sketch.ino** loaded.

### Installation
```bash
uv sync
```

### Running the Server
```bash
uv run python arduino_control.py
```

## Serial Protocol (Arduino Side)

The Arduino must implement the following command-response protocol at 9600 baud:

| Command | Action | Example Response |
| :--- | :--- | :--- |
| IDENT | Identify board | ID:RA4M1|Arduino Nano R4 |
| DR:<pin> | Digital Read | 1 or 0 |
| AR:<pin> | Analog Read | 512 (0-1023) |
| AR:I2C | Read TMP102 temperature | 24.50 |
| DW:<pin>:<val> | Digital Write | OK |
| AW:<pin>:<val> | Analog Write (PWM) | OK |
| DAC:<pin>:<val> | Set DAC Voltage | OK |

## Available MCP Tools

- `get_board_info`: restituisce MCU, porta seriale e FQBN della scheda.
- `get_device_mapping`: mostra la mappa device corrente.
- `get_pin_map`: restituisce la mappa dei pin standard supportati da Nano R4.
- `set_device_mapping`: mappa un nome logico a un pin fisico e definisce il tipo di dispositivo.
- `get_system_status`: legge lo stato dei dispositivi mappati.
- `control_actuator`: imposta un valore su output digitale, PWM o DAC.
- `read_sensor_data`: legge dati da un sensore specifico.
- `read_tmp102`: legge la temperatura direttamente dal TMP102 sul bus I2C.

## Hardware Setup (Requested Example)

Questa configurazione è specifica per Arduino Nano R4 con RGB LED onboard e sensore TMP102 sulla linea I2C.

- **LED BUILTIN**: Pin 13
- **LED Blue**: Pin 2
- **LED Red**: Pin 3
- **CC Motor**: Pin 9 (PWM)
- **TMP102 Sensor**: I2C Bus (Address 0x48), mappato come `I2C` nel firmware

## Development Conventions

- **Gestione dello stato**: il server mantiene `device_map` in memoria. Se il server viene riavviato, la mappatura deve essere reinviata dal client.
- **Logging**: tutti i log interni vengono inviati su `stderr`.
- **Tooling**: usare prima `set_device_mapping` per definire la configurazione hardware.
