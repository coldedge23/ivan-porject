import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart' as crypto;
import 'package:encrypt/encrypt.dart' as enc;
import 'package:hive_flutter/hive_flutter.dart';

import 'crypto_service.dart';

/// Phase 3：主密碼機制。
///
/// 金鑰不是隨便存起來的東西，而是每次用「你輸入的主密碼」+ 一組隨機鹽值（salt），
/// 透過 Argon2id（刻意設計得很慢、抗暴力破解的金鑰衍生演算法）現場算出來。
/// 我們不會、也沒辦法存下主密碼本身——只存了鹽值，跟一個用來「驗證密碼對不對」
/// 的加密驗證碼（verifier）。忘記主密碼 = 資料真的救不回來，這是刻意的設計。
class MasterPasswordService {
  static const _boxName = 'master_password_box';
  static const _saltKey = 'salt';
  static const _verifierKey = 'verifier';
  static const _verifyPlainText = 'master_password_ok';

  static final _argon2 = crypto.Argon2id(
    memory: 19456, // 19 MiB，OWASP 建議的互動式登入基準值
    parallelism: 1,
    iterations: 2,
    hashLength: 32, // AES-256 需要 32 bytes 的金鑰
  );

  static Future<Box> _box() => Hive.openBox(_boxName);

  static Future<bool> isSetUp() async {
    final box = await _box();
    return box.containsKey(_saltKey);
  }

  static List<int> _randomSalt() {
    final random = Random.secure();
    return List<int>.generate(16, (_) => random.nextInt(256));
  }

  static Future<enc.Key> _deriveKey(String password, List<int> salt) async {
    final secretKey = await _argon2.deriveKeyFromPassword(
      password: password,
      nonce: salt,
    );
    final keyBytes = await secretKey.extractBytes();
    return enc.Key(Uint8List.fromList(keyBytes));
  }

  /// 第一次使用：設定主密碼。
  static Future<void> setup(String password) async {
    final salt = _randomSalt();
    final key = await _deriveKey(password, salt);

    final encrypter = enc.Encrypter(enc.AES(key, mode: enc.AESMode.gcm));
    final iv = enc.IV.fromSecureRandom(12);
    final verifier = encrypter.encrypt(_verifyPlainText, iv: iv);

    final box = await _box();
    await box.put(_saltKey, base64Encode(salt));
    await box.put(_verifierKey, '${iv.base64}:${verifier.base64}');

    CryptoService.setActiveKey(key);
  }

  /// 輸入主密碼解鎖。成功會把金鑰設進 CryptoService 並回傳 true。
  static Future<bool> unlock(String password) async {
    final box = await _box();
    final saltBase64 = box.get(_saltKey) as String?;
    final verifierPayload = box.get(_verifierKey) as String?;
    if (saltBase64 == null || verifierPayload == null) return false;

    final salt = base64Decode(saltBase64);
    final key = await _deriveKey(password, salt);

    try {
      final parts = verifierPayload.split(':');
      final iv = enc.IV.fromBase64(parts[0]);
      final encrypted = enc.Encrypted.fromBase64(parts[1]);
      final encrypter = enc.Encrypter(enc.AES(key, mode: enc.AESMode.gcm));
      final decrypted = encrypter.decrypt(encrypted, iv: iv);
      if (decrypted != _verifyPlainText) return false;
    } catch (_) {
      // 密碼錯 → 衍生出來的金鑰跟著錯 → GCM 驗證失敗，直接視為密碼錯誤。
      return false;
    }

    CryptoService.setActiveKey(key);
    return true;
  }
}
