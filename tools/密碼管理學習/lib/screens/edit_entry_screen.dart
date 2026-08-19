import 'package:flutter/material.dart';

import '../models/password_entry.dart';

/// 新增/編輯畫面共用同一個表單。
/// existingEntry 為 null 代表「新增」，不為 null 代表「編輯」。
class EditEntryScreen extends StatefulWidget {
  const EditEntryScreen({super.key, this.existingEntry});

  final PasswordEntry? existingEntry;

  @override
  State<EditEntryScreen> createState() => _EditEntryScreenState();
}

class _EditEntryScreenState extends State<EditEntryScreen> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _titleController;
  late final TextEditingController _usernameController;
  late final TextEditingController _passwordController;
  late final TextEditingController _noteController;
  bool _obscurePassword = true;

  bool get _isEditing => widget.existingEntry != null;

  @override
  void initState() {
    super.initState();
    final entry = widget.existingEntry;
    _titleController = TextEditingController(text: entry?.title ?? '');
    _usernameController = TextEditingController(text: entry?.username ?? '');
    _passwordController = TextEditingController(text: entry?.password ?? '');
    _noteController = TextEditingController(text: entry?.note ?? '');
  }

  @override
  void dispose() {
    _titleController.dispose();
    _usernameController.dispose();
    _passwordController.dispose();
    _noteController.dispose();
    super.dispose();
  }

  void _save() {
    if (!_formKey.currentState!.validate()) return;

    final existing = widget.existingEntry;
    final entry = existing == null
        ? PasswordEntry(
            id: DateTime.now().microsecondsSinceEpoch.toString(),
            title: _titleController.text.trim(),
            username: _usernameController.text.trim(),
            password: _passwordController.text,
            note: _noteController.text.trim(),
            createdAt: DateTime.now(),
          )
        : existing.copyWith(
            title: _titleController.text.trim(),
            username: _usernameController.text.trim(),
            password: _passwordController.text,
            note: _noteController.text.trim(),
          );

    Navigator.of(context).pop(entry);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(_isEditing ? '編輯帳號' : '新增帳號')),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            TextFormField(
              controller: _titleController,
              decoration: const InputDecoration(
                labelText: '網站 / 服務名稱',
                hintText: '例如：Gmail、學校教務系統',
              ),
              validator: (value) =>
                  (value == null || value.trim().isEmpty) ? '請輸入名稱' : null,
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _usernameController,
              decoration: const InputDecoration(labelText: '帳號 / 信箱'),
              validator: (value) =>
                  (value == null || value.trim().isEmpty) ? '請輸入帳號' : null,
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _passwordController,
              obscureText: _obscurePassword,
              decoration: InputDecoration(
                labelText: '密碼',
                suffixIcon: IconButton(
                  icon: Icon(
                    _obscurePassword ? Icons.visibility : Icons.visibility_off,
                  ),
                  onPressed: () =>
                      setState(() => _obscurePassword = !_obscurePassword),
                ),
              ),
              validator: (value) =>
                  (value == null || value.isEmpty) ? '請輸入密碼' : null,
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _noteController,
              decoration: const InputDecoration(labelText: '備註（選填）'),
              maxLines: 3,
            ),
            const SizedBox(height: 24),
            FilledButton(
              onPressed: _save,
              child: const Text('儲存'),
            ),
          ],
        ),
      ),
    );
  }
}
