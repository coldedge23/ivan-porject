import 'package:flutter/material.dart';

import 'screens/setup_master_password_screen.dart';
import 'screens/unlock_screen.dart';
import 'services/entry_storage.dart';
import 'services/master_password_service.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await EntryStorage.init();
  final isSetUp = await MasterPasswordService.isSetUp();
  runApp(MyApp(isSetUp: isSetUp));
}

class MyApp extends StatelessWidget {
  const MyApp({super.key, required this.isSetUp});

  final bool isSetUp;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '密碼管理學習',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.deepPurple),
      ),
      home: isSetUp ? const UnlockScreen() : const SetupMasterPasswordScreen(),
    );
  }
}
