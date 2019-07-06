import functools
import grp
import os
import pwd
import urllib.parse

import psutil
import pyquota as pq
import requests
from flask import Flask, request, jsonify, send_from_directory

from auth_connect import oauth

app = Flask(__name__)

app.config.from_json('config.json')

oauth.init_app(app)

_quota_format_names = {
    1: 'vfsold',
    2: 'vfsv0',
    4: 'vfsv1'
}


def requires_api_key(f):
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        auth = request.authorization
        if not auth:
            return jsonify(msg='authorization required'), 401
        if auth.username != 'api' or auth.password != app.config['API_KEY']:
            return jsonify(msg='access forbidden'), 403
        return f(*args, **kwargs)

    return wrapped


@app.route('/')
@oauth.requires_login
def get_index_page():
    return app.send_static_file('index.html')


@app.route('/api/quotas')
@oauth.requires_admin
def get_quotas():
    results = {}
    for slave in app.config['SLAVES']:
        slave_id = slave['id']
        slave_url = slave['url']
        try:
            resp = requests.get('%s/remote-api/quotas' % slave_url, auth=_make_auth(slave))
            if resp.status_code // 100 != 2:
                results[slave_id] = dict(error=resp.json())
            else:
                results[slave_id] = dict(results=resp.json())
        except IOError as e:
            results[slave_id] = dict(error=dict(msg=str(e)))

    return jsonify(results)


@app.route('/api/quotas/<string:slave_id>/users/<int:uid>', methods=['PUT'])
@oauth.requires_admin
def set_user_quota(slave_id, uid):
    slave = None
    for _slave in app.config['SLAVES']:
        if _slave['id'] == slave_id:
            slave = _slave
            break

    if not slave:
        return jsonify(msg='slave not found'), 404

    device = request.args.get('device')
    try:
        resp = requests.put('%s/remote-api/quotas/users/%d?device=%s' % (slave['url'], uid, urllib.parse.quote(device)),
                            json=request.json, auth=_make_auth(slave))
        return jsonify(resp.json()), resp.status_code
    except IOError as e:
        return jsonify(msg=str(e)), 500


@app.route('/remote-api/quotas')
@requires_api_key
def remote_get_quotas():
    results = []

    devices = _get_devices()
    for device in devices.values():
        device_name = device['name']
        opts = device['opts']
        user_quotas = None
        group_quotas = None

        if 'usrquota' in opts:
            try:
                fmt = pq.get_user_quota_format(device_name)
                device['user_quota_format'] = _quota_format_names[fmt]
            except pq.APIError:
                pass

            try:
                bgrace, igrace, flags = pq.get_user_quota_info(device_name)
                device['user_quota_info'] = dict(block_grace=bgrace, inode_grace=igrace, flags=flags)
            except pq.APIError:
                pass

            user_quotas = []
            for entry in pwd.getpwall():
                uid = entry.pw_uid
                if uid < 1000 or uid == 65534:  # skip system users and nobody
                    continue
                try:
                    quota = pq.get_user_quota(device_name, uid)
                    quota_dict = _quota_tuple_to_dict(quota)
                    quota_dict['uid'] = uid
                    quota_dict['name'] = entry.pw_name
                    user_quotas.append(quota_dict)
                except pq.APIError:
                    pass

        if 'grpquota' in opts:
            try:
                fmt = pq.get_group_quota_format(device_name)
                device['group_quota_format'] = _quota_format_names[fmt]
            except pq.APIError:
                pass

            try:
                bgrace, igrace, flags = pq.get_group_quota_info(device_name)
                device['group_quota_info'] = dict(block_grace=bgrace, inode_grace=igrace, flags=flags)
            except pq.APIError:
                pass

            group_quotas = []
            for entry in grp.getgrall():
                gid = entry.gr_gid
                if gid < 1000 or gid == 65534:  # skip system groups and nogroup
                    continue
                try:
                    quota = pq.get_group_quota(device_name, gid)
                    quota_dict = _quota_tuple_to_dict(quota)
                    quota_dict['gid'] = gid
                    quota_dict['name'] = entry.gr_name
                    group_quotas.append(quota_dict)
                except pq.APIError:
                    pass

        if user_quotas is not None or group_quotas is not None:
            if user_quotas is not None:
                device['user_quotas'] = user_quotas
            if group_quotas is not None:
                device['group_quotas'] = group_quotas
            results.append(device)
    return jsonify(results)


@app.route('/remote-api/quotas/users/<int:uid>', methods=['PUT'])
@requires_api_key
def remote_set_user_quota(uid):
    params = request.json
    device = request.args.get('device')
    try:
        # set quota
        pq.set_user_quota(device, uid, params.get('block_hard_limit'), params.get('block_soft_limit'),
                          params.get('inode_hard_limit'), params.get('inode_soft_limit'))

        # get new quota
        quota = pq.get_user_quota(device, uid)
        quota_dict = _quota_tuple_to_dict(quota)
        quota_dict['uid'] = uid
        quota_dict['name'] = pwd.getpwuid(uid).pw_name

        return jsonify(quota_dict)
    except pq.APIError as e:
        return jsonify(msg=str(e)), 500


def _make_auth(slave):
    return "api", slave['api_key']


def _get_devices() -> dict:
    devices = {}
    for partition in psutil.disk_partitions():
        device = devices.get(partition.device)
        if device is None:
            device = {
                'name': partition.device,
                'mount_points': [],
                'fstype': partition.fstype,
                'opts': partition.opts.split(',')
            }
            devices[partition.device] = device
        device['mount_points'].append(partition.mountpoint)

    for device in devices.values():
        usage = psutil.disk_usage(device['mount_points'][0])
        device['usage'] = {
            'free': usage.free,
            'total': usage.total,
            'used': usage.used,
            'percent': usage.percent
        }
    return devices


def _quota_tuple_to_dict(quota: tuple) -> dict:
    bhard, bsoft, bcurrent, ihard, isoft, icurrent, btime, itime = quota
    return {
        'block_hard_limit': bhard,
        'block_soft_limit': bsoft,
        'block_current': bcurrent,
        'inode_hard_limit': ihard,
        'inode_soft_limit': isoft,
        'inode_current': icurrent,
        'block_time_limit': btime,
        'inode_time_limit': itime
    }


if __name__ == '__main__':
    app.run(port=8436)
