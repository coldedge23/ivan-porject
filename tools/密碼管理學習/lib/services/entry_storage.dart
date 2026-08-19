import 'package:hive_flutter/hive_flutter.dart';

import '../models/password_entry.dart';
import 'crypto_service.dart';

/// Phase 2：密碼欄位存進資料庫前會先加密，讀出來後才解密。
/// 畫面（screens/）完全不知道這件事，只跟 PasswordEntry 明文物件打交道，
/// 這就是把加密邏輯獨立成一層的好處。
///
/// Phase 3：加密金鑰改由 MasterPasswordService 在解鎖成功後設進
/// CryptoService，這裡不用再管金鑰從哪來。
class EntryStorage {
  static const _boxName = 'password_entries';

  static Future<void> init() async {
    await Hive.initFlutter();
    await Hive.openBox(_boxName);
  }

  static Box get _box => Hive.box(_boxName);

  static List<PasswordEntry> getAll() {
    final entries = _box.values.map((e) {
      final map = Map<dynamic, dynamic>.from(e as Map);
      map['password'] = CryptoService.decryptText(map['password'] as String);
      return PasswordEntry.fromMap(map);
    }).toList();
    entries.sort((a, b) => b.createdAt.compareTo(a.createdAt));
    return entries;
  }

  static Future<void> save(PasswordEntry entry) async {
    final map = entry.toMap();
    map['password'] = CryptoService.encryptText(entry.password);
    await _box.put(entry.id, map);
  }

  static Future<void> delete(String id) async {
    await _box.delete(id);
  }
}
