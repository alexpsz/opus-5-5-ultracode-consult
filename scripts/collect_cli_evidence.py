#!/usr/bin/env python3
"""Archive evidence from one recorded CLI run, offline and without changing it.

Only the receipt's single session and stream-observed tools are eligible. Native
tool content corroborates access, never comprehension, correctness or acceptance.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid

MAX_FILE = 32 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff', '.svg'}


class EvidenceError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(value, code):
    if not value:
        raise EvidenceError(code)


def absolute(value):
    path = Path(value)
    require(path.is_absolute() and str(path) == str(value) and
            '..' not in path.parts, 'CANONICAL_ABSOLUTE_PATH_REQUIRED')
    return path


def open_dir(path):
    """Walk with directory descriptors; never follow a parent or leaf symlink."""
    path = absolute(str(path))
    descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        return descriptor
    except FileNotFoundError:
        os.close(descriptor)
        raise
    except OSError:
        os.close(descriptor)
        raise EvidenceError('UNSAFE_OR_UNAVAILABLE_DIRECTORY') from None


def read_bytes(path):
    parent = open_dir(path.parent)
    try:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=parent)
        try:
            before = os.fstat(descriptor)
            require(stat.S_ISREG(before.st_mode), 'REGULAR_FILE_REQUIRED')
            require(before.st_size <= MAX_FILE, 'SOURCE_TOO_LARGE')
            with os.fdopen(descriptor, 'rb', closefd=False) as stream:
                data = stream.read(MAX_FILE + 1)
            after = os.fstat(descriptor)
            require(len(data) <= MAX_FILE, 'SOURCE_TOO_LARGE')
            require((before.st_size, before.st_mtime_ns, before.st_ino) ==
                    (after.st_size, after.st_mtime_ns, after.st_ino) and
                    len(data) == after.st_size, 'SOURCE_CHANGED_DURING_READ')
            return data
        finally:
            os.close(descriptor)
    except FileNotFoundError:
        raise
    except OSError:
        raise EvidenceError('UNSAFE_OR_UNAVAILABLE_FILE') from None
    finally:
        os.close(parent)


def parse_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeDecodeError):
        raise EvidenceError('INVALID_OR_TRUNCATED_JSON') from None


def records(data):
    require(bool(data.strip()), 'EMPTY_NATIVE_STREAM')
    try:
        single = parse_json(data)
    except EvidenceError as error:
        if error.code != 'INVALID_OR_TRUNCATED_JSON':
            raise
    else:
        require(isinstance(single, dict), 'NATIVE_OBJECT_REQUIRED')
        return [(1, single)]
    result = []
    for line, raw in enumerate(data.splitlines(), 1):
        if raw.strip():
            value = parse_json(raw)
            require(isinstance(value, dict), 'NATIVE_OBJECT_REQUIRED')
            result.append((line, value))
    return result


def content(value):
    """Return text and observed image payload; never copy base64 into summary."""
    if isinstance(value, str):
        return value, False
    if isinstance(value, list):
        texts, image = [], False
        for block in value:
            if not isinstance(block, dict):
                continue
            if block.get('type') == 'text' and isinstance(block.get('text'), str):
                texts.append(block['text'])
            if block.get('type') == 'image':
                source = block.get('source', {})
                image |= isinstance(source, dict) and bool(source.get('data') or source.get('url'))
        return '\n'.join(texts), image
    return '', False


def meaningful(text):
    text = re.sub(r'^(?:Created At|Completed At):[^\n]*\n?', '', text, flags=re.M).strip()
    text = re.sub(r'^(?:Title|Description|OG Description|Source|File Path|Total Lines|'
                  r'Total Bytes):[^\n]*\n?', '', text, flags=re.M).strip().strip('-').strip()
    if not text:
        return False
    if re.fullmatch(r'\d+ lines?,?\s+\d+ bytes?\.?', text, re.I):
        return False
    if text == 'The following is the entire, complete content of the requested file.':
        return False
    if 'has been saved to:' in text:
        return False
    # Native wrappers and counts establish that a tool responded, not its body.
    if re.match(r'^(?:Error executing tool\b|Error while executing tool\b|Error:\s)', text):
        return False
    return True


def denial(text):
    return bool(re.match(r'\s*(?:Error:\s*)?(?:Permission to use .+ has been denied\b|'
                         r'Permission denied\b|Access denied\b|Tool execution denied\b)', text, re.I))


def category(name, parameters):
    target = next((parameters[k] for k in ('file_path', 'AbsolutePath', 'path', 'Url', 'url')
                   if isinstance(parameters.get(k), str)), None)
    lower = name.lower()
    if 'image' in lower or (target and Path(target).suffix.lower() in IMAGE_SUFFIXES):
        return 'image', target
    if lower in ('websearch', 'webfetch', 'search_web', 'read_url_content'):
        return 'web', target
    if lower in ('read', 'read_file', 'view_file', 'read_file_text', 'view_file_outline'):
        return 'file', target
    return 'other', target


class Collector:
    def __init__(self, directory):
        self.directory = directory
        self.sources = []
        self.data = {}
        self.tools = {}
        self.denials = []
        self.boundaries = []
        self.session_observed = False

    def source(self, path):
        key = str(path)
        if key not in self.data:
            data = read_bytes(path)
            require(sum(len(v[1]) for v in self.data.values()) + len(data) <= MAX_TOTAL,
                    'EVIDENCE_TOO_LARGE')
            source_id = f'source-{len(self.sources) + 1:03d}'
            archive = f'evidence-archive/sources/{source_id}-{path.name}'
            self.sources.append(dict(source_id=source_id, path=key, archive_path=archive,
                                     bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
            self.data[key] = (source_id, data)
        return self.data[key]

    def tool(self, tool_id, name, parameters):
        require(isinstance(name, str) and bool(name), 'TOOL_NAME_REQUIRED')
        parameters = parameters if isinstance(parameters, dict) else {}
        kind, target = category(name, parameters)
        if tool_id not in self.tools:
            self.tools[tool_id] = dict(tool_id=tool_id, name=name, category=kind, target=target,
                                      call_observed=True, result_observed=False,
                                      native_content=False, status='unknown', content_extent='unknown',
                                      sources=[], boundaries=[], _success=False, _failed=False,
                                      _denied=False, _image=False, _fragment=False)
        require(self.tools[tool_id]['name'] == name, 'CONFLICTING_TOOL_IDENTITY')
        return self.tools[tool_id]

    @staticmethod
    def link(tool, source_id, line=None):
        value = dict(source_id=source_id)
        if line is not None:
            value['line'] = line
        if value not in tool['sources']:
            tool['sources'].append(value)

    def result(self, tool, value, success, failed=False, denied=False, partial=False):
        tool['result_observed'] = True
        text, image = content(value)
        tool['_success'] |= success
        tool['_failed'] |= failed
        denied = denied or denial(text)
        tool['_denied'] |= denied
        tool['_image'] |= image
        tool['_fragment'] |= partial
        body_observed = image or (tool['category'] != 'image' and meaningful(text))
        if success and not failed and not denied and body_observed:
            tool['native_content'] = True
            if tool['category'] == 'web':
                tool['_fragment'] = True

    def check_session(self, event, session):
        for key in ('session_id', 'conversation_id'):
            value = event.get(key)
            if value is not None:
                require(value == session, 'NATIVE_SESSION_MISMATCH')
                self.session_observed = True

    def stream(self, adviser, events, source_id, session):
        pending_results = []
        for line, event in events:
            kind = event.get('type') if adviser == 'opus' else event.get('event')
            payload = event if adviser == 'opus' else event.get(kind, {}) if isinstance(kind, str) else event
            require(isinstance(payload, dict), 'INVALID_NATIVE_ENVELOPE')
            self.check_session(event, session)
            self.check_session(payload, session)
            for field in ('permission_denials', 'denied_actions'):
                values = payload.get(field)
                if values:
                    self.denials.append(dict(source_id=source_id, line=line, field=field,
                                             details=values, attribution='native_aggregate'))
            if any(payload.get(k) is True for k in ('partial', 'truncated', 'timed_out', 'response_truncated')):
                self.boundaries.append('native_stream_reports_partial_or_timeout')
            if (adviser == 'gemini' and kind == 'step_update' and
                    payload.get('step_type') in ('tool', 'tool_call') and
                    isinstance(payload.get('tool_info'), dict)):
                info = payload['tool_info']
                index = payload.get('step_index')
                require(isinstance(index, int) and not isinstance(index, bool) and index >= 0,
                        'INVALID_STEP_INDEX')
                tool = self.tool(str(index), info.get('name'), info.get('parameters'))
                self.link(tool, source_id, line)
                state = payload.get('state')
                if state in ('DONE', 'ERROR', 'FAILED', 'DENIED', 'CANCELLED', 'CANCELED') or 'output' in info:
                    self.result(tool, info.get('output'), state == 'DONE',
                                failed=state in ('ERROR', 'FAILED', 'CANCELLED', 'CANCELED') or bool(info.get('error')),
                                denied=state == 'DENIED' or bool(info.get('denied_actions')),
                                partial=payload.get('partial') is True or info.get('truncated') is True)
            if adviser == 'opus':
                message = payload.get('message')
                blocks = message.get('content') if isinstance(message, dict) else None
                if not isinstance(blocks, list):
                    continue
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    if kind == 'assistant' and block.get('type') == 'tool_use':
                        identifier = block.get('id')
                        require(isinstance(identifier, str) and bool(identifier), 'TOOL_ID_REQUIRED')
                        tool = self.tool(identifier, block.get('name'), block.get('input'))
                        self.link(tool, source_id, line)
                    elif kind == 'user' and block.get('type') == 'tool_result':
                        pending_results.append((line, block))
        for line, block in pending_results:
            tool = self.tools.get(block.get('tool_use_id'))
            if tool is None:
                self.boundaries.append('unmatched_tool_result_not_attributed')
                continue
            self.link(tool, source_id, line)
            failed = block.get('is_error') is True
            self.result(tool, block.get('content'), not failed, failed=failed,
                        partial=block.get('truncated') is True)
        # Claude aggregate denials can identify a call. AGY aggregate action names
        # alone cannot distinguish successful and denied reads of the same type.
        for item in self.denials:
            if isinstance(item['details'], list):
                for denied in item['details']:
                    if isinstance(denied, dict) and denied.get('tool_use_id') in self.tools:
                        self.tools[denied['tool_use_id']]['_denied'] = True
        require(self.session_observed, 'NATIVE_SESSION_NOT_OBSERVED')

    def native(self, root, session):
        if not self.tools:
            return
        conversation = root / 'brain' / session
        transcript = conversation / '.system_generated/logs/transcript.jsonl'
        try:
            source_id, raw = self.source(transcript)
        except FileNotFoundError:
            self.boundaries.append('native_transcript_unavailable')
            return
        seen = set()
        for line, entry in records(raw):
            self.check_session(entry, session)
            index = entry.get('step_index')
            tool = self.tools.get(str(index)) if isinstance(index, int) and not isinstance(index, bool) else None
            if tool is None or entry.get('type') != 'GENERIC':
                continue
            require(index not in seen, 'DUPLICATE_NATIVE_STEP')
            seen.add(index)
            self.link(tool, source_id, line)
            text = entry.get('content') if isinstance(entry.get('content'), str) else ''
            state = entry.get('status')
            partial = 'content' in (entry.get('truncated_fields') or [])
            self.result(tool, text, state == 'DONE', failed=state in ('ERROR', 'FAILED'),
                        denied=state == 'DENIED', partial=partial)
            step = conversation / '.system_generated' / 'steps' / str(index)
            output = step / 'output.txt'
            candidates = [(text, source_id)]
            try:
                output_id, output_raw = self.source(output)
            except FileNotFoundError:
                pass
            else:
                self.link(tool, output_id)
                try:
                    output_text = output_raw.decode('utf-8')
                except UnicodeDecodeError:
                    raise EvidenceError('INVALID_NATIVE_CONTENT_UTF8') from None
                self.result(tool, output_text, state == 'DONE', partial=partial)
                candidates.append((output_text, output_id))
            # Only the native saved-body pointer is a file capability. Ordinary
            # source links and quoted paths inside fetched content are never opened.
            for value, _ in candidates:
                for match in re.finditer(r'has been saved to:\s*([^\r\n]+)', value):
                    destination = match.group(1).strip().strip('`')
                    path = absolute(destination)
                    require(path.parent == step and path.name == 'content.md', 'NATIVE_POINTER_ESCAPE')
                    body_id, body = self.source(path)
                    self.link(tool, body_id)
                    try:
                        body_text = body.decode('utf-8')
                    except UnicodeDecodeError:
                        raise EvidenceError('INVALID_NATIVE_CONTENT_UTF8') from None
                    # A fetched body is useful evidence; neither the pointer nor a
                    # "full content" label proves the whole remote page was saved.
                    self.result(tool, body_text, state == 'DONE', partial=True)

    def finish(self):
        for tool in self.tools.values():
            if tool['_denied']:
                tool['status'] = 'denied'
            elif tool['_failed']:
                tool['status'] = 'failed'
            elif tool['category'] == 'image' or tool['_image']:
                tool['boundaries'].append('image_content_or_visual_understanding_not_verified_from_text')
            elif tool['_success'] and tool['native_content']:
                tool['status'] = 'corroborated'
            if tool['_fragment']:
                tool['content_extent'] = 'fragment'
                tool['boundaries'].append('partial_content_does_not_establish_complete_source_coverage')
            if tool['result_observed'] and not tool['native_content']:
                tool['boundaries'].append('status_or_metadata_only_without_source_content')
            if tool['native_content']:
                tool['boundaries'].append('source_access_does_not_establish_comprehension_or_factual_acceptance')
            for key in list(tool):
                if key.startswith('_'):
                    del tool[key]

    def archive(self, summary):
        descriptor = open_dir(self.directory)
        try:
            for name in ('evidence-summary.json', 'evidence-archive'):
                try:
                    os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                raise EvidenceError('EVIDENCE_ALREADY_EXISTS')
            os.mkdir('evidence-archive', mode=0o700, dir_fd=descriptor)
            archive_fd = os.open('evidence-archive', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                 dir_fd=descriptor)
            try:
                os.mkdir('sources', mode=0o700, dir_fd=archive_fd)
                sources_fd = os.open('sources', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                     dir_fd=archive_fd)
                try:
                    for source in self.sources:
                        name = Path(source['archive_path']).name
                        self.write(sources_fd, name, self.data[source['path']][1])
                finally:
                    os.close(sources_fd)
            finally:
                os.close(archive_fd)
            self.write(descriptor, 'evidence-summary.json',
                       (json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8'))
        finally:
            os.close(descriptor)

    @staticmethod
    def write(descriptor, name, data):
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600,
                     dir_fd=descriptor)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())


def collect(run_dir, native_data_root=None):
    directory = absolute(str(run_dir))
    collector = Collector(directory)
    _, receipt_raw = collector.source(directory / 'run.json')
    receipt = parse_json(receipt_raw)
    require(isinstance(receipt, dict), 'RECEIPT_OBJECT_REQUIRED')
    adviser, sessions = receipt.get('adviser'), receipt.get('session_ids')
    require(adviser in ('opus', 'gemini'), 'UNKNOWN_ADVISER')
    require(isinstance(sessions, list) and len(sessions) == 1 and isinstance(sessions[0], str),
            'EXACTLY_ONE_RECORDED_SESSION_REQUIRED')
    session = sessions[0]
    try:
        require(str(uuid.UUID(session)) == session, 'CANONICAL_SESSION_UUID_REQUIRED')
    except ValueError:
        raise EvidenceError('CANONICAL_SESSION_UUID_REQUIRED') from None
    stream_id, raw = collector.source(directory / 'stdout.raw')
    if receipt.get('stdout_sha256'):
        require(hashlib.sha256(raw).hexdigest() == receipt['stdout_sha256'], 'STREAM_HASH_MISMATCH')
    collector.stream(adviser, records(raw), stream_id, session)
    for name in ('stderr.raw', 'answer.md'):
        try:
            _, data = collector.source(directory / name)
        except FileNotFoundError:
            continue
        expected = receipt.get('stderr_sha256' if name == 'stderr.raw' else 'answer_sha256')
        if expected:
            require(hashlib.sha256(data).hexdigest() == expected, 'RECORDED_SOURCE_HASH_MISMATCH')
    if adviser == 'gemini':
        root = absolute(str(native_data_root or (Path.home() / '.gemini/antigravity-cli')))
        collector.native(root, session)
    if receipt.get('process_status') != 'SUCCESS':
        collector.boundaries.append('run_not_recorded_as_successful_terminal_process')
    collector.finish()
    summary = dict(schema_version=1, created_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                   request_id=receipt.get('request_id'), adviser=adviser, session_id=session,
                   recorded_delivery_status=receipt.get('delivery_status'), content_accepted=False,
                   tools=list(collector.tools.values()), native_denials=collector.denials,
                   boundaries=sorted(set(collector.boundaries)), sources=collector.sources)
    summary['coverage'] = {kind: {status: sum(t['category'] == kind and t['status'] == status
                                            for t in summary['tools'])
                                 for status in ('corroborated', 'denied', 'failed', 'unknown')}
                           for kind in ('file', 'web', 'image', 'other')}
    collector.archive(summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--native-data-root')
    args = parser.parse_args(argv)
    try:
        summary = collect(args.run_dir, args.native_data_root)
        print(json.dumps(dict(summary_path=str(Path(args.run_dir) / 'evidence-summary.json'),
                              coverage=summary['coverage'], content_accepted=False)))
        return 0
    except (EvidenceError, OSError) as error:
        print(json.dumps({'error_code': getattr(error, 'code', 'EVIDENCE_IO_ERROR')}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
