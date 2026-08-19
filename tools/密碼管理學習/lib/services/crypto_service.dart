import 'package:encrypt/encrypt.dart';

/// Phase 3：金鑰不再自己隨機產生後存起來，
/// 而是由 MasterPasswordService 在你輸入正確主密碼後才設進來，
/// 只存在記憶體裡，APP 關掉或按「鎖定」就會消失。
class CryptoService {
  static Encrypter? _encrypter;

  static void setActiveKey(Key key) {
    _encrypter = Encrypter(AES(key, mode: AESMode.gcm));
  }

  static void lock() {
    _encrypter = null;
  }

  static bool get isUnlocked => _encrypter != null;

  /// 回傳格式：base64(IV) + ':' + base64(密文)
  /// 每次加密都重新產生亂數 IV，絕對不能重複使用同一組 IV。
  static String encryptText(String plainText) {
    final iv = IV.fromSecureRandom(12);
    final encrypted = _encrypter!.encrypt(plainText, iv: iv);
    return '${iv.base64}:${encrypted.base64}';
  }

  static String decryptText(String cipherPayload) {
    final parts = cipherPayload.split(':');
    final iv = IV.fromBase64(parts[0]);
    final encrypted = Encrypted.fromBase64(parts[1]);
    return _encrypter!.decrypt(encrypted, iv: iv);
  }
}
