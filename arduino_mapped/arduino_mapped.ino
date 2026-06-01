#include <Wire.h>

// TMP102 I2C Address
#define TMP102_ADDR 0x48

#define BOARD_ID "ID:RA4M1|Arduino Nano R4"

void setup() {
  Serial.begin(9600);
  Wire.begin();

  // Standard setup for requested pins
  pinMode(LED_BUILTIN, OUTPUT);


    pinMode(LEDR, OUTPUT);
    pinMode(LEDG, OUTPUT);
    pinMode(LEDB, OUTPUT);
    // On Nano R4, RGB LEDs are common anode, write HIGH to turn OFF
    digitalWrite(LEDR, HIGH);
    digitalWrite(LEDG, HIGH);
    digitalWrite(LEDB, HIGH);
 
    pinMode(9, OUTPUT); // CC Motor (PWM)

    
}

int getPin(String pinStr) {
  if (pinStr == "LEDR") return LEDR;
  if (pinStr == "LEDG") return LEDG;
  if (pinStr == "LEDB") return LEDB;
  if (pinStr == "LED_BUILTIN") return LED_BUILTIN;
  if (pinStr.startsWith("A")) {
    int aPin = pinStr.substring(1).toInt();
    switch(aPin) {
      case 0: return A0; case 1: return A1; case 2: return A2;
      case 3: return A3; case 4: return A4; case 5: return A5;
      case 6: return A6; case 7: return A7;
      
    }
  }
  return pinStr.toInt();
}

void loop() {
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    Serial.println(cmd);

    if (cmd == "MAP") {
      Serial.println("MAP:LED_BUILTIN=13,LEDR=LEDR,LEDG=LEDG,LEDB=LEDB,CC_MOTOR=9,A0=DAC,I2C=TMP102");
    } 
    else if (cmd == "IDENT") {
      Serial.println(BOARD_ID);
    } 
    else if (cmd.startsWith("DR:")) {
      String pinStr = cmd.substring(3);
      Serial.println(digitalRead(getPin(pinStr)));
    } 
    else if (cmd.startsWith("DW:")) {
      int firstColon = cmd.indexOf(':', 3);
      Serial.println(firstColon);
      String pinStr = cmd.substring(3, firstColon);
      Serial.print(getPin(pinStr));
      int val = cmd.substring(firstColon + 1).toInt();
      Serial.println(val);
      Serial.println(getPin(pinStr));
        // RGB LEDs on Nano R4 are active LOW
        if (pinStr == "LEDR" || pinStr == "LEDG" || pinStr == "LEDB") {
           digitalWrite(getPin(pinStr), val == 1 ? LOW : HIGH);
        } else {
           digitalWrite(getPin(pinStr), val);
        }
      Serial.println("OK");
    } 
    else if (cmd.startsWith("AR:")) {
      String pinStr = cmd.substring(3);
      if (pinStr == "I2C") {
        Serial.println(readTMP102());
      } else {
        Serial.println(analogRead(getPin(pinStr)));
      }
    } 
    else if (cmd.startsWith("AW:")) {
      int firstColon = cmd.indexOf(':', 3);
      String pinStr = cmd.substring(3, firstColon);
      int val = cmd.substring(firstColon + 1).toInt();


        if (pinStr == "LEDR" || pinStr == "LEDG" || pinStr == "LEDB") {
           analogWrite(getPin(pinStr), 255 - val); // PWM inverted for common anode
        } else {
           analogWrite(getPin(pinStr), val);
        }
      Serial.println("OK");
    }
    else if (cmd.startsWith("DAC:")) {
      #if defined(ARDUINO_UNOR4_WIFI) || defined(ARDUINO_UNOR4_MINIMA) || defined(ARDUINO_NANO_R4)
        int firstColon = cmd.indexOf(':', 4);
        String valStr = cmd.substring(firstColon + 1);
        float voltage = valStr.toFloat();
        int dacVal = (voltage / 5.0) * 4095;
        analogWrite(PIN_A0, dacVal); 
        Serial.println("OK");
      #else
        Serial.println("ERR: No DAC");
      #endif
    }
  }
}

float readTMP102() {
  Wire.beginTransmission(TMP102_ADDR);
  Wire.write(0x00);
  Wire.endTransmission();
  Wire.requestFrom(TMP102_ADDR, 2);

  if (Wire.available() == 2) {
    byte msb = Wire.read();
    byte lsb = Wire.read();
    int res = ((msb << 4) | (lsb >> 4));
    return res * 0.0625;
  }
  return -1.0;
}
