/*
 * NÖBET — Faz 2 Donanım Doğrulama (ARŞİV)
 * ========================================
 * Bu klasör derlenmez (PlatformIO yalnızca src/ derler).
 * Donanımdan şüphelenildiğinde src/main.cpp yerine geçici olarak
 * kopyalanıp yüklenir: kablolamayı ve UID okumayı sade biçimde doğrular.
 *
 * Faz 2 sonucu (2026-08-08): VersionReg=0x92 · A1B2C3D4 · B5C6D7E8
 */

#include <Arduino.h>
#include <SPI.h>
#include <MFRC522.h>

#define RC522_SS   5
#define RC522_RST  22

MFRC522 mfrc(RC522_SS, RC522_RST);

String  lastUid  = "";
uint32_t lastMs  = 0;
const uint32_t DEBOUNCE_MS = 2000;
uint32_t readCount = 0;

String uidToHex(MFRC522::Uid *uid) {
  String s = "";
  for (byte i = 0; i < uid->size; i++) {
    if (uid->uidByte[i] < 0x10) s += "0";
    s += String(uid->uidByte[i], HEX);
  }
  s.toUpperCase();
  return s;
}

void selfTest() {
  byte v = mfrc.PCD_ReadRegister(MFRC522::VersionReg);
  Serial.print("[..] RC522 VersionReg = 0x");
  Serial.println(v, HEX);
  if (v == 0x00 || v == 0xFF) {
    Serial.println("[!!] HATA: Okuyucuya ulasilamiyor.");
    Serial.println("     1. 3.3V'a takili mi? (5V RC522'yi yakar)");
    Serial.println("     2. SDA=D5  RST=D22  SCK=D18  MOSI=D23  MISO=D19");
    Serial.println("     3. GND ortak mi?");
    Serial.println("     4. Jumper kablolar tam oturmus mu? (en sik sebep)");
    return;
  }
  Serial.print("[OK] RC522 hazir. Surum: ");
  if      (v == 0x91) Serial.println("v1.0");
  else if (v == 0x92) Serial.println("v2.0");
  else                Serial.println("bilinmeyen klon (calisabilir)");
}

void setup() {
  Serial.begin(115200);
  delay(600);
  Serial.println();
  Serial.println("========================================");
  Serial.println("  NOBET — RC522 Dogrulama");
  Serial.println("========================================");
  SPI.begin();
  mfrc.PCD_Init();
  delay(50);
  selfTest();
  mfrc.PCD_SetAntennaGain(MFRC522::RxGain_max);
  Serial.println("----------------------------------------");
  Serial.println("Kartlari tek tek okutun...");
  Serial.println();
}

void loop() {
  if (!mfrc.PICC_IsNewCardPresent()) return;
  if (!mfrc.PICC_ReadCardSerial())   return;

  String uid = uidToHex(&mfrc.uid);
  uint32_t now = millis();
  if (uid == lastUid && (now - lastMs) < DEBOUNCE_MS) {
    mfrc.PICC_HaltA();
    return;
  }
  lastUid = uid;
  lastMs  = now;
  readCount++;

  MFRC522::PICC_Type type = mfrc.PICC_GetType(mfrc.uid.sak);
  Serial.print(">> #");      Serial.print(readCount);
  Serial.print("  UID: ");   Serial.print(uid);
  Serial.print("   (");      Serial.print(mfrc.uid.size);
  Serial.print(" byte, ");   Serial.print(MFRC522::PICC_GetTypeName(type));
  Serial.print(", SAK=0x");  Serial.print(mfrc.uid.sak, HEX);
  Serial.print(", uptime="); Serial.print(now);
  Serial.println("ms)");

  mfrc.PICC_HaltA();
  mfrc.PCD_StopCrypto1();
}
