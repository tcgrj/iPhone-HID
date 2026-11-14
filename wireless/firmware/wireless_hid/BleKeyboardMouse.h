#pragma once

#include <Arduino.h>
#include <NimBLEDevice.h>
#include <NimBLEHIDDevice.h>
#include <atomic>

enum class MouseButton : uint8_t { Left = 1, Right = 2, Middle = 4 };

// BLE only: no USB HID or camera GPIO dependency. Commands run on one task.
// A true result means reports were accepted by NimBLE, not that iOS acted on them.
class BleKeyboardMouse : private NimBLEServerCallbacks, private NimBLECharacteristicCallbacks {
 public:
  void begin() {
    static uint8_t reportMap[] = {
      0x05,0x01, 0x09,0x02, 0xa1,0x01, 0x85,0x01, 0x09,0x01, 0xa1,0x00,
      0x05,0x09, 0x19,0x01, 0x29,0x03, 0x15,0x00, 0x25,0x01, 0x95,0x03,
      0x75,0x01, 0x81,0x02, 0x95,0x01, 0x75,0x05, 0x81,0x03,
      0x05,0x01, 0x09,0x30, 0x09,0x31, 0x09,0x38, 0x15,0x81, 0x25,0x7f,
      0x75,0x08, 0x95,0x03, 0x81,0x06, 0xc0, 0xc0,
      0x05,0x01, 0x09,0x06, 0xa1,0x01, 0x85,0x02,
      0x05,0x07, 0x19,0xe0, 0x29,0xe7, 0x15,0x00, 0x25,0x01, 0x75,0x01,
      0x95,0x08, 0x81,0x02, 0x95,0x01, 0x75,0x08, 0x81,0x03,
      0x95,0x06, 0x75,0x08, 0x15,0x00, 0x25,0x65, 0x19,0x00, 0x29,0x65,
      0x81,0x00, 0xc0,
    };
    NimBLEDevice::init("TechGe Wireless iPhone");
    NimBLEDevice::setSecurityAuth(BLE_SM_PAIR_AUTHREQ_BOND | BLE_SM_PAIR_AUTHREQ_SC);
    NimBLEDevice::setSecurityIOCap(BLE_HS_IO_NO_INPUT_OUTPUT);
    auto* server = NimBLEDevice::createServer();
    server->setCallbacks(this, false);
    server->advertiseOnDisconnect(true);
    auto* hid = new NimBLEHIDDevice(server);
    hid->setManufacturer("TechGe prototype");
    // Unassigned prototype identifiers; do not impersonate an Apple peripheral.
    hid->setPnp(0x02, 0, 0, 0x0001);
    hid->setHidInfo(0, 1);
    hid->setReportMap(reportMap, sizeof(reportMap));
    mouseReport_ = hid->getInputReport(1);
    keyboardReport_ = hid->getInputReport(2);
    mouseReport_->setCallbacks(this);
    keyboardReport_->setCallbacks(this);
    hid->setBatteryLevel(100);
    hid->startServices();
    auto* advertising = NimBLEDevice::getAdvertising();
    advertising->setAppearance(0x03c0);
    advertising->setName("TechGe Wireless iPhone");
    advertising->addServiceUUID(hid->getHidService()->getUUID());
    advertising->enableScanResponse(true);
    advertising->start();
  }

  bool isPaired() const { return paired_; }
  bool mouseReady() const { return paired_ && mouseSubscribed_; }
  bool keyboardReady() const { return paired_ && keyboardSubscribed_; }
  uint32_t generation() const { return generation_; }

  bool move(int x, int y) {
    return sendMouse(x, y, generation_, handle_);
  }
  bool press(MouseButton button) {
    if (!mouseReady()) return false;
    const uint32_t epoch = generation_;
    const uint16_t peer = handle_;
    buttons_ |= static_cast<uint8_t>(button);
    if (sendMouse(0, 0, epoch, peer)) return true;
    buttons_ = 0;
    sendMouse(0, 0, epoch, peer);
    return false;
  }
  bool release(MouseButton button) {
    const uint32_t epoch = generation_;
    const uint16_t peer = handle_;
    buttons_ &= ~static_cast<uint8_t>(button);
    return sendMouse(0, 0, epoch, peer);
  }
  bool click(MouseButton button, uint16_t holdMs = 30) {
    const uint32_t epoch = generation_;
    const uint16_t peer = handle_;
    if (!samePeer(epoch, peer) || !mouseSubscribed_) return false;
    buttons_ |= static_cast<uint8_t>(button);
    if (!sendMouse(0, 0, epoch, peer)) {
      buttons_ = 0;
      sendMouse(0, 0, epoch, peer);
      return false;
    }
    delay(constrain(holdMs, 15, 250));
    buttons_ &= ~static_cast<uint8_t>(button);
    return sendMouse(0, 0, epoch, peer);
  }

  bool type(const uint8_t* text, size_t length) {
    if (!keyboardReady() || !text || length == 0 || length > 40) return false;
    for (size_t i = 0; i < length; ++i) {
      if (text[i] < 32 || text[i] > 126 || !asciiKey(text[i])) return false;
    }
    const uint32_t epoch = generation_;
    const uint16_t peer = handle_;
    const uint8_t released[8] = {};
    for (size_t i = 0; i < length; ++i) {
      const uint8_t code = asciiKey(text[i]);
      const uint8_t pressed[8] = {uint8_t((code & 0x80) ? 0x02 : 0), 0, uint8_t(code & 0x7f)};
      if (!sendKeyboard(pressed, epoch, peer)) {
        sendKeyboard(released, epoch, peer);
        return false;
      }
      delay(20);
      if (!sendKeyboard(released, epoch, peer)) {
        delay(20);
        sendKeyboard(released, epoch, peer);
        return false;
      }
      delay(20);
    }
    return samePeer(epoch, peer) && keyboardReady();
  }

 private:
  static uint8_t asciiKey(uint8_t c) {
    if (c >= 'a' && c <= 'z') return 4 + c - 'a';
    if (c >= 'A' && c <= 'Z') return (4 + c - 'A') | 0x80;
    if (c >= '1' && c <= '9') return 30 + c - '1';
    if (c == '0') return 39;
    const char plain[] = " -=[]\\;\x27`,./";
    const char shifted[] = "_+{}|:\"~<>?";
    const uint8_t plainCodes[] = {44,45,46,47,48,49,51,52,53,54,55,56};
    for (size_t i = 0; i < sizeof(plain) - 1; ++i) if (c == plain[i]) return plainCodes[i];
    for (size_t i = 0; i < sizeof(shifted) - 1; ++i) if (c == shifted[i]) return plainCodes[i + 1] | 0x80;
    const char numberShift[] = "!@#$%^&*()";
    for (size_t i = 0; i < sizeof(numberShift) - 1; ++i) if (c == numberShift[i]) return (30 + i) | 0x80;
    return 0;
  }
  bool samePeer(uint32_t epoch, uint16_t peer) const {
    return peer != BLE_HS_CONN_HANDLE_NONE && paired_ && generation_ == epoch && handle_ == peer;
  }
  bool sendMouse(int x, int y, uint32_t epoch, uint16_t peer) {
    if (!samePeer(epoch, peer) || !mouseSubscribed_ || x < -127 || x > 127 || y < -127 || y > 127) return false;
    const uint8_t report[4] = {buttons_, uint8_t(x), uint8_t(y), 0};
    return mouseReport_->notify(report, sizeof(report), peer) && samePeer(epoch, peer) && mouseSubscribed_;
  }
  bool sendKeyboard(const uint8_t* report, uint32_t epoch, uint16_t peer) {
    return samePeer(epoch, peer) && keyboardSubscribed_ && keyboardReport_->notify(report, 8, peer)
           && samePeer(epoch, peer) && keyboardSubscribed_;
  }
  void onConnect(NimBLEServer* server, NimBLEConnInfo& info) override {
    if (handle_ != BLE_HS_CONN_HANDLE_NONE) {
      server->disconnect(info.getConnHandle());
      return;
    }
    generation_++;
    paired_ = mouseSubscribed_ = keyboardSubscribed_ = false;
    buttons_ = 0;
    handle_ = info.getConnHandle();
    server->updateConnParams(handle_, 24, 40, 0, 400);
  }
  void onAuthenticationComplete(NimBLEConnInfo& info) override {
    if (info.getConnHandle() != handle_) return;
    if (!info.isEncrypted()) {
      NimBLEDevice::getServer()->disconnect(info.getConnHandle());
      return;
    }
    paired_ = true;
    NimBLEDevice::getServer()->updateConnParams(handle_, 12, 12, 0, 400);
  }
  void onSubscribe(NimBLECharacteristic* characteristic, NimBLEConnInfo& info, uint16_t value) override {
    if (info.getConnHandle() != handle_) return;
    if (characteristic == mouseReport_) {
      mouseSubscribed_ = value & 1;
      buttons_ = 0;
      if (mouseReady()) sendMouse(0, 0, generation_, handle_);
    } else if (characteristic == keyboardReport_) {
      keyboardSubscribed_ = value & 1;
      const uint8_t released[8] = {};
      if (keyboardReady()) sendKeyboard(released, generation_, handle_);
    }
  }
  void onDisconnect(NimBLEServer*, NimBLEConnInfo& info, int) override {
    if (info.getConnHandle() != handle_) return;
    paired_ = false;
    generation_++;
    mouseSubscribed_ = keyboardSubscribed_ = false;
    buttons_ = 0;
    handle_ = BLE_HS_CONN_HANDLE_NONE;
  }

  std::atomic<uint32_t> generation_{0};
  std::atomic<uint16_t> handle_{BLE_HS_CONN_HANDLE_NONE};
  std::atomic<bool> paired_{false};
  std::atomic<bool> mouseSubscribed_{false};
  std::atomic<bool> keyboardSubscribed_{false};
  std::atomic<uint8_t> buttons_{0};
  NimBLECharacteristic* mouseReport_ = nullptr;
  NimBLECharacteristic* keyboardReport_ = nullptr;
};
