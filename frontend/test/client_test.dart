import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:planner_hub/api/client.dart';

http.Response reply(int status, Object body) => http.Response.bytes(
    utf8.encode(jsonEncode(body)), status, headers: {'content-type': 'application/json'});

void main() {
  test('an expired sign-in is refreshed once and retried', () async {
    final seen = <String?>[];
    final refreshes = <bool>[];
    final api = ApiClient(
      baseUrl: 'http://test',
      token: ({refresh = false}) async {
        refreshes.add(refresh);
        return refresh ? 'fresh' : 'stale';
      },
      httpClient: MockClient((req) async {
        seen.add(req.headers['Authorization']);
        return req.headers['Authorization'] == 'Bearer fresh'
            ? reply(200, {'auth': 'firebase', 'email': 'a@b.c', 'uid': 'u'})
            : reply(401, {'message': 'Firebase sign-in expired; sign in again'});
      }),
    );
    expect((await api.me())['auth'], 'firebase');
    expect(seen, ['Bearer stale', 'Bearer fresh']);
    expect(refreshes, [false, true]);
  });

  test('a refused account reports the server message', () async {
    String? rejected;
    final api = ApiClient(
      baseUrl: 'http://test',
      token: ({refresh = false}) async => 't',
      onUnauthorized: (m) => rejected = m,
      httpClient: MockClient((_) async =>
          reply(401, {'message': "x@y.z isn't allowed to use Planner Hub"})),
    );
    await expectLater(api.me(), throwsA(isA<ApiException>()));
    expect(rejected, "x@y.z isn't allowed to use Planner Hub");
  });

  test('503 is retried, then succeeds', () async {
    var calls = 0;
    final api = ApiClient(
      baseUrl: 'http://test',
      token: ({refresh = false}) async => 't',
      retryDelays: const [Duration.zero, Duration.zero],
      httpClient: MockClient((_) async =>
          ++calls < 3 ? reply(503, {'message': "couldn't reach Google"}) : reply(200, {'auth': 'owner'})),
    );
    expect((await api.me())['auth'], 'owner');
    expect(calls, 3);
  });

  test('network failure becomes a readable error', () async {
    final api = ApiClient(
      baseUrl: 'http://test',
      token: ({refresh = false}) async => 't',
      httpClient: MockClient((_) async => throw http.ClientException('offline')),
    );
    await expectLater(api.me(), throwsA(predicate((e) => e is ApiException && e.status == 0)));
  });
}
