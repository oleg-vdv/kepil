# MCP-сервер Kepil в контейнере.
#
# Нужен каталогам вроде Glama, которые запускают сервер и спрашивают у него
# список инструментов. Ничего, кроме этого, образ не делает: панель оператора
# сюда не входит намеренно — она слушает localhost и выставлять её наружу
# отдельным контейнером было бы приглашением это сделать неправильно.
#
# Зависимостей нет: ставится один пакет с PyPI, всё остальное — стандартная
# библиотека Python.
#
#   docker build -t kepil-mcp .
#   docker run --rm -i kepil-mcp
#
# Проверка вручную — сервер обязан ответить на два сообщения:
#   printf '%s\n' \
#     '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
#     '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
#     | docker run --rm -i kepil-mcp

FROM python:3.11-slim

# Версия пакета задаётся при сборке, чтобы образ не «уезжал» вслед за PyPI.
ARG KEPIL_VERSION=0.3.1

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    KEPIL_DATA=/var/lib/kepil

RUN pip install --no-cache-dir "kepil==${KEPIL_VERSION}"

# Журнал и паспорта переживают перезапуск только на смонтированном томе.
# Без него контейнер стартует и отвечает на интроспекцию, но всё написанное
# исчезнет вместе с ним — для проверки каталогом этого достаточно, для работы
# нет.
VOLUME ["/var/lib/kepil"]

# Отдельный пользователь: сервер не должен работать от root даже здесь.
RUN useradd --system --create-home --uid 10001 kepil \
    && mkdir -p /var/lib/kepil \
    && chown -R kepil:kepil /var/lib/kepil
USER kepil

# Протокол идёт через стандартный ввод-вывод, поэтому порты не публикуются.
ENTRYPOINT ["python", "-m", "kepil.mcp"]
