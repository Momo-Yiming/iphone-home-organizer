#!/usr/bin/env python3
"""Private, device-specific iPhone layout snapshots and verified writes."""

import argparse
import asyncio
import base64
import hashlib
import io
import json
import plistlib
import sys
from collections import Counter, defaultdict, deque
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def die(message):
    raise ValueError(message)


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    path.chmod(0o600)


def save_plist(path, value):
    path.write_bytes(plistlib.dumps(value, fmt=plistlib.FMT_BINARY))
    path.chmod(0o600)
    if plistlib.loads(path.read_bytes()) != value:
        die(f'Backup could not be parsed: {path}')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def app_key(item):
    return item.get('bundleIdentifier') or item['displayIdentifier']


def leaves(state):
    for page in state:
        for item in page:
            if item is False:
                continue
            if item.get('listType') == 'folder':
                yield from leaves(item['iconLists'])
            else:
                yield item


def layout_shape(state):
    pages = []
    for page in state:
        row = []
        for item in page:
            if item is False:
                continue  # iOS 18+ compacts gaps on write.
            if item.get('listType') == 'folder':
                row.append(('folder', item['displayName'], tuple(app_key(i) for i in leaves(item['iconLists']))))
            else:
                row.append(('app', app_key(item)))
        pages.append(tuple(row))
    return tuple(pages)


def read_snapshot(directory):
    return (plistlib.loads((directory / 'snapshot.plist').read_bytes()),
            json.loads((directory / 'device.json').read_text(encoding='utf-8')))


def inventory_rows(state):
    rows = {}
    for page_number, page in enumerate(state):
        for item in page:
            if item is False:
                continue
            base = 'Dock' if page_number == 0 else f'Page {page_number}'
            if item.get('listType') == 'folder':
                entries = [(app, f'{base}/{item["displayName"]}/{folder_page + 1}')
                           for folder_page, folder_items in enumerate(item['iconLists'])
                           for app in folder_items]
            else:
                entries = [(item, base)]
            for app, location in entries:
                key = app_key(app)
                row = rows.setdefault(key, {'key': key, 'name': app.get('displayName') or key,
                                            'count': 0, 'locations': []})
                row['count'] += 1
                row['locations'].append(location)
    return list(rows.values())


def draft(state):
    pages = []
    for n, page in enumerate(state[1:], 1):
        items = []
        for item in page:
            if item is False:
                items.append({'empty': True})
            elif item.get('listType') == 'folder':
                items.append({'folder': item['displayName'],
                              'apps': [app_key(app) for app in leaves(item['iconLists'])]})
            else:
                items.append({'app': app_key(item)})
        pages.append({'title': f'第 {n} 页', 'items': items})
    dock = []
    for item in state[0]:
        if item.get('listType') == 'folder':
            dock.append({'folder': item['displayName'],
                         'apps': [app_key(app) for app in leaves(item['iconLists'])]})
        else:
            dock.append(app_key(item))
    return {'dock': dock, 'pages': pages}


def build(state, metrics, plan):
    rows, columns = int(metrics['homeScreenIconRows']), int(metrics['homeScreenIconColumns'])
    folder_capacity = int(metrics['homeScreenIconFolderRows']) * int(metrics['homeScreenIconFolderColumns'])
    folder_limit = folder_capacity * int(metrics['homeScreenIconFolderMaxPages'])
    if not isinstance(plan, dict) or not isinstance(plan.get('dock'), list) or not isinstance(plan.get('pages'), list):
        die('Plan needs ordered dock and pages arrays')
    if not plan['pages'] or len(plan['pages']) > int(metrics['homeScreenIconMaxPages']):
        die('Page count exceeds device limit')
    if len(plan['dock']) > int(metrics['homeScreenIconDockMaxCount']):
        die('Dock exceeds device limit')

    records = defaultdict(deque)
    for app in leaves(state):
        records[app_key(app)].append(app)

    def take(identifier):
        if not isinstance(identifier, str) or not records[identifier]:
            die(f'Unknown or overused app identifier: {identifier}')
        return records[identifier].popleft()

    def place(spec, allow_empty=True):
        if isinstance(spec, str):
            return take(spec)
        if not isinstance(spec, dict):
            die('Each item must be an app identifier or object')
        if set(spec) == {'app'}:
            return take(spec['app'])
        if set(spec) == {'folder', 'apps'}:
            if not isinstance(spec['folder'], str) or not spec['folder'] or not isinstance(spec['apps'], list):
                die('Folder needs a name and apps array')
            if not 1 <= len(spec['apps']) <= folder_limit:
                die(f'Folder capacity exceeded: {spec["folder"]}')
            contents = [take(identifier) for identifier in spec['apps']]
            return {'displayName': spec['folder'], 'listType': 'folder',
                    'iconLists': [contents[i:i + folder_capacity]
                                  for i in range(0, len(contents), folder_capacity)]}
        if allow_empty and spec == {'empty': True}:
            return False
        die(f'Unsupported item: {spec}')

    result = [[place(entry, allow_empty=False) for entry in plan['dock']]]
    for page in plan['pages']:
        if not isinstance(page, dict) or not isinstance(page.get('items'), list):
            die('Each page needs an ordered items array')
        items = [place(spec) for spec in page['items']]
        if len(items) > rows * columns:
            die(f'Page exceeds {rows} × {columns} grid')
        result.append(items)

    if any(records.values()):
        die('Plan omitted original entries: ' + ', '.join(k for k, values in records.items() if values))
    source_records = Counter(plistlib.dumps(app) for app in leaves(state))
    target_records = Counter(plistlib.dumps(app) for app in leaves(result))
    if source_records != target_records:
        die('Native icon records differ from source')
    return result


async def connected(serial=None):
    from pymobiledevice3.lockdown import create_using_usbmux
    return await create_using_usbmux(serial=serial, connection_type='USB', autopair=False)


async def snapshot_command(directory, serial=None):
    from pymobiledevice3.services.springboard import SpringBoardServicesService
    if directory.exists():
        die(f'Directory already exists: {directory}')
    directory.mkdir(parents=True, mode=0o700)
    try:
        async with await connected(serial) as lockdown:
            async with SpringBoardServicesService(lockdown) as sb:
                state = await sb.get_icon_state()
                metrics = await sb.get_homescreen_icon_metrics()
            save_plist(directory / 'snapshot.plist', state)
            save_json(directory / 'device.json', {'udid': lockdown.udid,
                       'model': lockdown.product_type, 'ios': lockdown.product_version,
                       'metrics': metrics, 'snapshot_sha256': digest(directory / 'snapshot.plist')})
    except Exception:
        # Keep a possible partial snapshot for inspection; never overwrite a retry.
        raise
    print(json.dumps({'directory': str(directory), 'pages': len(state) - 1,
                      'entries': sum(1 for _ in leaves(state)), 'unique': len(inventory_rows(state))}, ensure_ascii=False))


async def icons_command(directory):
    from pymobiledevice3.services.springboard import SpringBoardServicesService
    state, info = read_snapshot(directory)
    images = directory / 'icons'
    images.mkdir(mode=0o700, exist_ok=True)
    saved = 0
    async with await connected(info['udid']) as lockdown:
        async with SpringBoardServicesService(lockdown) as sb:
            for row in inventory_rows(state):
                key = row['key']
                path = images / (hashlib.sha256(key.encode()).hexdigest() + '.png')
                if path.exists():
                    continue
                try:
                    image = await sb.get_icon_pngdata(key)
                    if image and image.startswith(b'\x89PNG'):
                        path.write_bytes(image)
                        path.chmod(0o600)
                        saved += 1
                except Exception:
                    continue  # System shortcuts and web clips can lack PNG data.
    print(json.dumps({'saved': saved, 'directory': str(images)}, ensure_ascii=False))


def icon_data(directory, key):
    path = directory / 'icons' / (hashlib.sha256(key.encode()).hexdigest() + '.png')
    if not path.exists():
        return None
    try:
        from PIL import Image
        with Image.open(path) as image:
            image = image.convert('RGB').resize((64, 64), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            image.save(out, format='WEBP', quality=70)
            return 'data:image/webp;base64,' + base64.b64encode(out.getvalue()).decode()
    except ImportError:
        return 'data:image/png;base64,' + base64.b64encode(path.read_bytes()).decode()


def prepare_command(directory, plan_path):
    state, info = read_snapshot(directory)
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    target = build(state, info['metrics'], plan)
    target_path = directory / 'proposed.plist'
    save_plist(target_path, target)
    if plistlib.loads(target_path.read_bytes()) != target:
        die('Proposed layout failed round trip')
    inventory = inventory_rows(state)
    names = {row['key']: row['name'] for row in inventory}
    usage_path = directory / 'usage.json'
    usage = json.loads(usage_path.read_text(encoding='utf-8')) if usage_path.exists() else {}
    if not isinstance(usage, dict) or any(key not in names or not isinstance(value, dict) for key, value in usage.items()):
        die('usage.json must map known app identifiers to metric objects')
    keys = list(names)
    data = {'plan': plan, 'names': names, 'locations': {row['key']: row['locations'] for row in inventory},
            'usage': usage, 'icons': {key: icon_data(directory, key) for key in keys},
            'entries': sum(1 for _ in leaves(state)), 'unique': len(keys),
            'grid': {'rows': info['metrics']['homeScreenIconRows'],
                     'columns': info['metrics']['homeScreenIconColumns']}}
    raw = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    template = (HERE / 'assets/preview.html').read_text(encoding='utf-8')
    (directory / 'preview.html').write_text(template.replace('__PREVIEW_DATA__', raw), encoding='utf-8')
    (directory / 'preview.html').chmod(0o600)
    review = {'status': 'preview_only', 'device_model': info['model'], 'ios': info['ios'],
              'pages': len(target) - 1, 'entries': data['entries'], 'unique': data['unique'],
              'dock': [names[entry] if isinstance(entry, str) else
                       names[entry['app']] if 'app' in entry else entry['folder']
                       for entry in plan['dock']],
              'page_titles': [page.get('title') or f'第 {n} 页' for n, page in enumerate(plan['pages'], 1)],
              'proposed_sha256': digest(target_path), 'source_sha256': info['snapshot_sha256'],
              'gap_note': 'iOS may compact empty slots on write'}
    save_json(directory / 'review.json', review)
    print(json.dumps(review, ensure_ascii=False))


async def write_command(directory, target, source, restore=False):
    from pymobiledevice3.services.springboard import SpringBoardServicesService
    _, info = read_snapshot(directory)
    wanted = plistlib.loads(target.read_bytes())
    original = plistlib.loads(source.read_bytes())
    async with await connected(info['udid']) as lockdown:
        if lockdown.udid != info['udid']:
            die('Different device connected')
        async with SpringBoardServicesService(lockdown) as sb:
            before = await sb.get_icon_state()
        if not restore and layout_shape(before) != layout_shape(original):
            die('The phone layout changed since snapshot; re-read before writing')
        if not restore and Counter(map(app_key, leaves(before))) != Counter(map(app_key, leaves(wanted))):
            die('Proposed layout does not contain every current icon')
        run = directory / (('restore-' if restore else 'write-') + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        run.mkdir(mode=0o700)
        save_plist(run / 'before.plist', before)
        save_plist(run / 'requested.plist', wanted)
        save_json(run / 'device.json', info)
        print('Verified backup:', run / 'before.plist', flush=True)
        async with SpringBoardServicesService(lockdown) as sb:
            await sb.service.send_plist({'command': 'setIconState', 'iconState': wanted})
        print('Write sent; checking a new connection.', flush=True)
        for attempt, delay in enumerate((1, 3, 6), 1):
            await asyncio.sleep(delay)
            async with SpringBoardServicesService(lockdown) as sb:
                actual = await sb.get_icon_state()
            save_plist(run / f'readback-{attempt}.plist', actual)
            extra = Counter(map(app_key, leaves(actual))) - Counter(map(app_key, leaves(wanted)))
            missing = Counter(map(app_key, leaves(wanted))) - Counter(map(app_key, leaves(actual)))
            matched = layout_shape(actual) == layout_shape(wanted)
            status = 'verified' if matched else 'extra_apps' if extra and not missing else 'mismatch'
            report = {'status': status, 'attempt': attempt, 'pages': len(actual) - 1,
                      'entries': sum(1 for _ in leaves(actual)), 'unique': len(set(map(app_key, leaves(actual)))),
                      'extra': dict(extra), 'missing': dict(missing),
                      'backup': str(run / 'before.plist'), 'readback': str(run / f'readback-{attempt}.plist')}
            save_json(run / 'verification.json', report)
            print(json.dumps(report, ensure_ascii=False), flush=True)
            if matched:
                return 0
        return 4 if report['status'] == 'extra_apps' else 3


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command', required=True)
    snapshot = commands.add_parser('snapshot', help='Read a connected USB phone')
    snapshot.add_argument('--out', required=True, type=Path)
    snapshot.add_argument('--udid', help='Select one USB phone when several are connected')
    for name in ('inventory', 'draft', 'icons', 'prepare', 'apply', 'restore'):
        command = commands.add_parser(name)
        command.add_argument('--dir', required=True, type=Path)
        if name == 'prepare':
            command.add_argument('--plan', required=True, type=Path)
        if name == 'apply':
            command.add_argument('--approved-sha', required=True)
        if name == 'restore':
            command.add_argument('--backup', required=True, type=Path)
            command.add_argument('--approved', action='store_true', required=True)
    return p


def main():
    args = parser().parse_args()
    if args.command == 'snapshot':
        asyncio.run(snapshot_command(args.out, args.udid))
        return
    directory = args.dir.resolve()
    if args.command == 'inventory':
        state, _ = read_snapshot(directory)
        rows = inventory_rows(state)
        save_json(directory / 'inventory.json', rows)
        print(json.dumps({'apps': len(rows), 'entries': sum(row['count'] for row in rows),
                          'path': str(directory / 'inventory.json')}, ensure_ascii=False))
    elif args.command == 'draft':
        state, _ = read_snapshot(directory)
        path = directory / 'plan.json'
        if path.exists():
            die(f'Existing plan will not be overwritten: {path}')
        save_json(path, draft(state))
        print(path)
    elif args.command == 'icons':
        asyncio.run(icons_command(directory))
    elif args.command == 'prepare':
        prepare_command(directory, args.plan)
    elif args.command == 'apply':
        review = json.loads((directory / 'review.json').read_text(encoding='utf-8'))
        proposed = directory / 'proposed.plist'
        state_path = directory / 'snapshot.plist'
        if digest(proposed) != args.approved_sha or review['proposed_sha256'] != args.approved_sha:
            die('Approved proposal hash does not match current proposed layout')
        if digest(state_path) != review['source_sha256']:
            die('Snapshot changed after review')
        return asyncio.run(write_command(directory, proposed, state_path))
    elif args.command == 'restore':
        backup = args.backup.resolve()
        if not backup.is_relative_to(directory):
            die('Restore file must be inside this device work directory')
        return asyncio.run(write_command(directory, backup, directory / 'snapshot.plist', restore=True))


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, KeyError, ValueError, IndexError, TypeError) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(2)
