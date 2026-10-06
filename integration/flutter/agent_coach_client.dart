import 'dart:async';
import 'dart:convert';
import 'dart:io';

/// Transport errors preserve the service code so the App can choose a local fallback.
class AgentCoachException implements Exception {
  const AgentCoachException(this.code, this.message, {this.retryable = false, this.statusCode});

  final String code;
  final String message;
  final bool retryable;
  final int? statusCode;

  @override
  String toString() => 'AgentCoachException($code, $message)';
}

/// Network-only adapter. Map these responses to the App's existing Dart models.
class AgentCoachClient {
  AgentCoachClient({
    required Uri baseUrl,
    HttpClient? httpClient,
    this.connectTimeout = const Duration(seconds: 5),
    this.responseTimeout = const Duration(seconds: 30),
    this.devToken,
  })  : _baseUrl = baseUrl.toString().endsWith('/') ? baseUrl : Uri.parse('${baseUrl.toString()}/'),
        _http = httpClient ?? HttpClient();

  final Uri _baseUrl;
  final HttpClient _http;
  final Duration connectTimeout;
  final Duration responseTimeout;
  final String? devToken;

  /// Keep this local. Native training must be blocked by the App when discomfort is true.
  static Map<String, Object?> projectProfile(Map<String, dynamic> profile) {
    const fields = <String>{
      'schema_version', 'goal', 'experience', 'days_per_week',
      'minutes_per_session', 'has_equipment', 'diet_preference',
    };
    if (!profile.keys.toSet().containsAll(fields)) {
      throw const AgentCoachException('INVALID_PROFILE', '画像缺少必要字段。');
    }
    return {for (final key in fields) key: profile[key]};
  }

  static Map<String, Object?> projectSession(Map<String, dynamic> session) {
    const fields = <String>{
      'schema_version', 'session_id', 'status', 'finished_at',
      'duration_seconds', 'exercises', 'agent_summary',
      'next_plan_changed', 'source',
    };
    if (!session.keys.toSet().containsAll(fields)) {
      throw const AgentCoachException('INVALID_SESSION', '训练结果缺少桥协议字段。');
    }
    final rawExercises = session['exercises'];
    if (rawExercises is! List) {
      throw const AgentCoachException('INVALID_SESSION', '训练动作列表无效。');
    }
    const exerciseFields = <String>{
      'exercise_id', 'completed_sets', 'completed_reps',
      'quality_trend', 'main_error_code',
    };
    final exercises = rawExercises.map((value) {
      if (value is! Map<String, dynamic> ||
          !value.keys.toSet().containsAll(exerciseFields)) {
        throw const AgentCoachException('INVALID_SESSION', '训练动作字段不完整。');
      }
      return {for (final key in exerciseFields) key: value[key]};
    }).toList(growable: false);
    return {...{for (final key in fields) key: session[key]}, 'exercises': exercises};
  }

  Future<Map<String, dynamic>> capabilities() => _request('GET', 'capabilities');

  Future<Map<String, dynamic>> fetchPlan(
    Map<String, dynamic> profile,
    List<Map<String, dynamic>> history, {
    List<String> executableExercises = const ['squat'],
    DateTime? localDate,
  }) {
    if (profile['has_current_discomfort'] == true) {
      throw const AgentCoachException('LOCAL_TRAINING_PAUSED', '当前不适，应由 APP 保持本地暂停安排。');
    }
    return _request('POST', 'plan', {
      'profile': projectProfile(profile),
      'history': history.map(projectSession).toList(growable: false),
      'executable_exercises': executableExercises,
      'local_date': (localDate ?? DateTime.now()).toIso8601String().substring(0, 10),
    });
  }

  Future<Map<String, dynamic>> fetchNutrition(Map<String, dynamic> profile) =>
      _request('POST', 'nutrition', {'profile': projectProfile(profile)});

  Future<Map<String, dynamic>> fetchWeeklyProgress({
    required Map<String, dynamic> profile,
    required List<Map<String, dynamic>> history,
    DateTime? localDate,
  }) => _request('POST', 'progress/weekly', {
        'profile': projectProfile(profile),
        'history': history.map(projectSession).toList(growable: false),
        'local_date': (localDate ?? DateTime.now()).toIso8601String().substring(0, 10),
      });

  /// installationId is a stable random UUID stored locally by the App.
  Future<Map<String, dynamic>> fetchSummary({
    required String installationId,
    required Map<String, dynamic> profile,
    required Map<String, dynamic> session,
    List<Map<String, dynamic>> history = const [],
  }) => _request('POST', 'sessions/summary', {
        'installation_id': installationId,
        'profile': projectProfile(profile),
        'session': projectSession(session),
        'history': history.map(projectSession).toList(growable: false),
      });

  Future<Map<String, dynamic>> deleteCachedSummaries(String installationId) =>
      _request('POST', 'data/delete', {'installation_id': installationId});

  Future<Map<String, dynamic>> _request(
    String method,
    String path, [
    Map<String, Object?>? payload,
  ]) async {
    try {
      final uri = _baseUrl.resolve(path);
      if (uri.scheme != 'https' && !(uri.scheme == 'http' &&
          (uri.host == '127.0.0.1' || uri.host == 'localhost'))) {
        throw const AgentCoachException('INSECURE_ENDPOINT', '正式服务必须使用 HTTPS。');
      }
      final request = await _http.openUrl(method, uri).timeout(connectTimeout);
      request.headers.contentType = ContentType.json;
      request.headers.set(HttpHeaders.acceptHeader, 'application/json');
      if (devToken != null) request.headers.set(HttpHeaders.authorizationHeader, 'Bearer $devToken');
      if (payload != null) request.write(jsonEncode(payload));
      final response = await request.close().timeout(responseTimeout);
      final text = await utf8.decoder.bind(response).join().timeout(responseTimeout);
      final decoded = jsonDecode(text);
      if (decoded is! Map<String, dynamic>) {
        throw const AgentCoachException('INVALID_RESPONSE', '服务返回的 JSON 不是对象。');
      }
      if (response.statusCode >= 400) {
        final detail = decoded['detail'];
        final error = detail is Map<String, dynamic> ? detail : <String, dynamic>{};
        throw AgentCoachException(
          error['code'] is String ? error['code'] as String : 'HTTP_${response.statusCode}',
          error['message'] is String ? error['message'] as String : '服务暂不可用。',
          retryable: error['retryable'] == true,
          statusCode: response.statusCode,
        );
      }
      return decoded;
    } on AgentCoachException {
      rethrow;
    } on TimeoutException {
      throw const AgentCoachException('NETWORK_TIMEOUT', '请求超时。', retryable: true);
    } on SocketException {
      throw const AgentCoachException('NETWORK_UNAVAILABLE', '无法连接服务。', retryable: true);
    } on FormatException {
      throw const AgentCoachException('INVALID_RESPONSE', '服务返回了无效 JSON。');
    } on HttpException {
      throw const AgentCoachException('NETWORK_UNAVAILABLE', 'HTTP 连接失败。', retryable: true);
    }
  }

  void close() => _http.close(force: true);
}
