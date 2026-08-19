class PasswordEntry {
  final String id;
  final String title;
  final String username;
  final String password;
  final String note;
  final DateTime createdAt;

  PasswordEntry({
    required this.id,
    required this.title,
    required this.username,
    required this.password,
    this.note = '',
    required this.createdAt,
  });

  PasswordEntry copyWith({
    String? title,
    String? username,
    String? password,
    String? note,
  }) {
    return PasswordEntry(
      id: id,
      title: title ?? this.title,
      username: username ?? this.username,
      password: password ?? this.password,
      note: note ?? this.note,
      createdAt: createdAt,
    );
  }

  Map<String, dynamic> toMap() => {
        'id': id,
        'title': title,
        'username': username,
        'password': password,
        'note': note,
        'createdAt': createdAt.toIso8601String(),
      };

  factory PasswordEntry.fromMap(Map<dynamic, dynamic> map) => PasswordEntry(
        id: map['id'] as String,
        title: map['title'] as String,
        username: map['username'] as String,
        password: map['password'] as String,
        note: map['note'] as String? ?? '',
        createdAt: DateTime.parse(map['createdAt'] as String),
      );
}
