#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2019/3/7 13:15
# @Author  : Fred Yangxiaofei
# @File    : send_handler.py
# @Role    : AlertManager发送警告路由


import tornado.web
import json
from libs.database import db_session, model_to_dict
from models.alert import PrometheusAlert
from websdk.utils import SendSms, SendMail
from websdk.consts import const
from websdk.tools import convert
from websdk.configs import configs
from websdk.db_context import DBContext
from biz.write_redis import redis_conn


class AlterHanlder(tornado.web.RequestHandler):
    def get(self, *args, **kwargs):
        key = self.get_argument('key', default=None, strip=True)
        value = self.get_argument('value', default=None, strip=True)
        project_list = []
        with DBContext('w') as session:
            if key and value:
                alert_data = session.query(PrometheusAlert).filter_by(**{key: value}).all()
            else:
                alert_data = session.query(PrometheusAlert).all()

        for data in alert_data:
            data_dict = model_to_dict(data)
            data_dict['create_at'] = str(data_dict['create_at'])
            data_dict['update_at'] = str(data_dict['update_at'])
            project_list.append(data_dict)
        return self.write(dict(code=0, msg='获取成功', data=project_list))

    def post(self, *args, **kwargs):
        data = json.loads(self.request.body.decode("utf-8"))
        keyword = data.get('keyword')
        alert_level = data.get('alert_level', '未定义')
        config_file = data.get('config_file')

        if not keyword:
            return self.write(dict(code=-2, msg='关键参数不能为空'))

        with DBContext('w', None, True) as session:
            is_exist = session.query(PrometheusAlert.id).filter(
                PrometheusAlert.keyword == keyword).first()

            if is_exist:
                return self.write(dict(code=-2, msg='名称不能重复'))

            session.add(PrometheusAlert(keyword=keyword, alert_level=alert_level, config_file=config_file))

        self.write(dict(code=0, msg='添加成功'))

    def delete(self, *args, **kwargs):
        data = json.loads(self.request.body.decode("utf-8"))
        alert_id = data.get('alert_id', None)
        if not alert_id:
            return self.write(dict(code=-1, msg='ID不能为空'))

        with DBContext('w', None, True) as session:
            session.query(PrometheusAlert).filter(PrometheusAlert.id == alert_id).delete(synchronize_session=False)

        self.write(dict(code=0, msg='删除成功'))

    def put(self, *args, **kwargs):
        data = json.loads(self.request.body.decode("utf-8"))
        alert_id = data.get('id', None)
        keyword = data.get('keyword')
        alert_level = data.get('alert_level', '未定义')
        config_file = data.get('config_file')

        if not keyword:
            return self.write(dict(code=-1, msg='规则名称不能为空'))

        with DBContext('w', None, True) as session:
            session.query(PrometheusAlert).filter(PrometheusAlert.id == alert_id).update(
                {PrometheusAlert.keyword: keyword, PrometheusAlert.alert_level: alert_level,
                 PrometheusAlert.config_file: config_file})
            session.commit()
        self.write(dict(code=0, msg='编辑成功'))

    def patch(self, *args, **kwargs):
        data = json.loads(self.request.body.decode("utf-8"))
        alert_id = data.get('alert_id', None)
        nicknames = data.get('nicknames', None)

        if not nicknames:
            return self.write(dict(code=-1, msg='不能为空'))

        with DBContext('w', None, True) as session:
            session.query(PrometheusAlert).filter(PrometheusAlert.id == alert_id).update(
                {PrometheusAlert.nicknames: nicknames})
            session.commit()
        self.write(dict(code=0, msg='关联用户成功'))


class SendHanlder(tornado.web.RequestHandler):

    def post(self, *args, **kwargs):
        data = json.loads(self.request.body.decode("utf-8"))
        alerts = data.get('alerts')  # 获取AlertManager POST报警数据
        for alerts_data in alerts:
            labels = alerts_data.get('labels')
            alert_name = labels.get('alertname')
            cache_conn = redis_conn()

            cache_config_info = cache_conn.hgetall(const.APP_SETTINGS)
            if  cache_config_info:
                config_info = convert(cache_config_info)
            else:
                config_info =configs['email_info']

            emails_list = cache_conn.hvals(alert_name)
            sm = SendMail(mail_host=config_info.get(const.EMAIL_HOST), mail_port=config_info.get(const.EMAIL_PORT),
                          mail_user=config_info.get(const.EMAIL_HOST_USER),
                          mail_password=config_info.get(const.EMAIL_HOST_PASSWORD),
                          mail_ssl=True if config_info.get(const.EMAIL_USE_SSL) == '1' else False)
            ### 如果没有redis没有配置
            if not emails_list:
                sm.send_mail(configs.get('default_email'), alert_name, alerts_data['annotations']['detail'])
                return self.write(dict(code=-1, msg="没有匹配到规则"))

            ### 默认发送邮件
            sm.send_mail(",".join(emails_list), alert_name, alerts_data['annotations']['detail'])

            # 严重警告发短信
            if labels.get('severity') == "严重":
                if not configs.get('sign_name') or not  configs.get('template_code'):
                    sm.send_mail(configs.get('default_email'), alert_name, '请配置短信的sign_name和template_code')
                else:
                    phone_numbers = cache_conn.hkeys(alert_name)
                    # 发送内容
                    params = {"msg": alerts_data['annotations']['detail']}
                    sms = SendSms(config_info.get(const.SMS_REGION), config_info.get(const.SMS_DOMAIN),
                                  config_info.get(const.SMS_PRODUCT_NAME), config_info.get(const.SMS_ACCESS_KEY_ID),
                                  config_info.get(const.SMS_ACCESS_KEY_SECRET))

                    sms.send_sms(phone_numbers=",".join(phone_numbers), template_param=params,
                                 sign_name=configs.get('sign_name'), template_code=configs.get('template_code'))

        return self.write(dict(code=0, msg="发送成功", data=alerts))


alert_urls = [
    (r"/v1/tools/alert/prometheus/", AlterHanlder),
    (r"/v1/tools/send/prometheus/", SendHanlder),
]
