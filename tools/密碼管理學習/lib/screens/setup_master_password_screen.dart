import 'package:flutter/material.dart';

import '../services/master_password_service.dart';
import 'home_screen.dart';

class SetupMasterPasswordScreen extends StatefulWidget {
  const SetupMasterPasswordScreen({super.key});

  @override
  State<SetupMasterPasswordScreen> createState() =>
      _SetupMasterPasswordScreenState();
}

class _SetupMasterPasswordScreenState
    extends State<SetupMasterPasswordScreen> {
  final _formKey = GlobalKey<FormState>();
  final _passwordController = TextEditingController();
  final _confirmController = TextEditingController();
  bool _isWorking = false;

  @override
  void dispose() {
    _passwordController.dispose();
    _confirmController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _isWorking = true);

    await MasterPasswordService.setup(_passwordController.text);

    if (!mounted) return;
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => const HomeScreen()),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('設定主密碼')),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            const Text(
              '這是第一次使用，請設定一組主密碼。\n\n'
              '之後每次打開 APP 都需要輸入這組密碼才能看到你的帳號密碼資料。\n\n'
              '⚠️ 沒有人（包括開發者）能幫你找回忘記的主密碼，請務必記住它。',
            ),
            const SizedBox(height: 20),
            TextFormField(
              controller: _passwordController,
              obscureText: true,
              decoration: const InputDecoration(labelText: '主密碼'),
              validator: (value) =>
                  (value == null || value.length < 4) ? '至少輸入 4 個字元' : null,
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _confirmController,
              obscureText: true,
              decoration: const InputDecoration(labelText: '再輸入一次確認'),
              validator: (value) =>
                  value != _passwordController.text ? '兩次輸入不一致' : null,
            ),
            const SizedBox(height: 24),
            FilledButton(
              onPressed: _isWorking ? null : _submit,
              child: _isWorking
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Text('設定完成'),
            ),
          ],
        ),
      ),
    );
  }
}
