#!/usr/bin/env python
import requests
import hipchat
import consulate
import smtplib
import string
from slacker import Slacker
from multiprocessing import Process
from Settings import Settings

class NotificationEngine(Settings):

    """
    NotificationEngine, routes given ConsulHealthNodeStruct objects
    using the plugins available and based off tags in ConsulHealthNodeStruct.
    ConsulHealthNodeStruct is an python object representation of
        {
        "Node": "foobar",
        "CheckID": "service:redis",
        "Name": "Service 'redis' check",
        "Status": "passing",
        "Tags": [],
        "Notes": "",
        "Output": "",
        "ServiceID": "redis",
        "ServiceName": "redis"
        }

    Example use:

        NotificationEngine([ConsulHealthNodeStruct,ConsulHealthNodeStruct]).Run()
    """

    def __init__(self, alert_list,consul_host="0.0.0.0"):
        """consul_watch_handler_checks, will send a list of ConsulHealthNodeStruct
        :param list alert_list: of ConsulHealthNodeStruct Object
        """
        super(NotificationEngine,self).__init__()
        self.alert_list = alert_list
        self.session = consulate.Consulate(consul_host)
        # eventually load these values some other way


    def __getattr__(self, item):
        return None

    def get_available_plugins(self):
        self.available_plugins = set(self.session.kv[NotificationEngine.KV_ALERTING_AVAILABLE_PLUGINS])
        return self.available_plugins

    def get_unique_tags_keys(self):
        """
         find unique tags in the list of ConsulHealthNodeStruct objects, used to determine which plugins to load
        """

        # python 2.6 syntax
        self.unique_tags = set(
            tag for obj in self.alert_list for tag in obj.Tags)

        return self.unique_tags

    def load_plugins_from_tags(self):
        # set intersection of unique_tags and available_plugins
        configurations_files_to_load = self.unique_tags.intersection(
            self.available_plugins)


        if "hipchat" in configurations_files_to_load:
            self.hipchat = self.load_plugin(NotificationEngine.KV_ALERTING_NOTIFY_HIPCHAT,"rooms")

        if "slack" in configurations_files_to_load:
            self.slack = self.load_plugin(NotificationEngine.KV_ALERTING_NOTIFY_SLACK,"rooms")

        if "mailgun" in configurations_files_to_load:
            self.mailgun = self.load_plugin(NotificationEngine.KV_ALERTING_NOTIFY_MAILGUN,"teams")

        if "email" in configurations_files_to_load:
            self.email = self.load_plugin(NotificationEngine.KV_ALERTING_NOTIFY_EMAIL,"teams")


        return (self.hipchat,self.slack,self.mailgun,self.email)



    @staticmethod
    def dict_keys_to_low(dictionary):
        dict_keys_lowercase = dict((key.lower(), value)
                                for key, value in dictionary.iteritems())

        return dict_keys_lowercase

    def load_plugin(self,KV_LOCATION,tags_dictname):
        # get request to 0.0.0.0:8500/v1/kv/notify/<plugin_name> which routes to
        # consul master
        plugin = self.session.kv[KV_LOCATION]

        # Convert Keys to lower case
        plugin = NotificationEngine.dict_keys_to_low(plugin)

        plugin[tags_dictname] = dict(
                (key.lower(), value) for key, value in plugin[tags_dictname].iteritems())

        return plugin


    def common_notifiers(self,obj,kv_tags_dictname,kv_dict):
        keynames = set(kv_dict[kv_tags_dictname].keys())
        obj_tags = set(obj.Tags)

        common = keynames.intersection(obj_tags)

        return common

    def message_pattern(self,obj):

        if obj.ServiceName or obj.ServiceID:

            message_template = "Service {name}: is in a {state} state on {node}. " \
                               "Output from test: {output}".format(name=obj.ServiceName,
                                                                   state=obj.Status,
                                                                   node=obj.Node,
                                                                   output=obj.Output)

        else:

            message_template = "System Check {name}: is in a {state} state on {node}. " \
                               "Output from test: {output}".format(name=obj.CheckID,
                                                                   state=obj.Status,
                                                                   node=obj.Node,
                                                                   output=obj.Output)

        return message_template

    def run_notifiers(self,obj):

        message_template = self.message_pattern(obj)

        if "hipchat" in obj.Tags and self.hipchat:
            common_notifiers = self.common_notifiers(obj,"rooms",self.hipchat)
            hipchat = self.hipchat
            Process(target=notify_hipchat,args=(obj,message_template,common_notifiers,hipchat)).start()


        if "slack" in obj.Tags and self.slack:
            common_notifiers = self.common_notifiers(obj,"rooms",self.slack)
            slack =self.slack
            Process(target=notify_slack,args=(obj,message_template,common_notifiers,slack)).start()


        if "mailgun" in obj.Tags and self.mailgun:
            common_notifiers = self.common_notifiers(obj,"teams",self.mailgun)
            mailgun = self.mailgun
            Process(target=notify_mailgun,args=(obj,message_template,common_notifiers,mailgun)).start()


        if "email" in obj.Tags and self.email:
            common_notifiers = self.common_notifiers(obj,"teams",self.email)
            email = self.email
            Process(target=notify_email,args=(obj,message_template,common_notifiers,email)).start()



    def Run(self):
        self.get_available_plugins()
        self.get_unique_tags_keys()
        self.load_plugins_from_tags()

        for obj in self.alert_list:
            self.run_notifiers(obj)





def notify_hipchat(obj, message_template,common_notifiers,consul_hipchat):
    #common_hipchat_rooms = self.common_notifiers(obj,"rooms",self.hipchat)

    # Use hipchat library to use for notifications requires api_token and
    # url
    hipster = hipchat.HipChat(
        token=consul_hipchat["api_token"], url=consul_hipchat["url"])

    for roomname in common_notifiers:

        if obj.Status == NotificationEngine.PASSING_STATE:
            color_value = "green"
            notify_value = 0

        elif obj.Status == NotificationEngine.WARNING_STATE:
            color_value = "yellow"
            notify_value = 1

        elif obj.Status == NotificationEngine.CRITICAL_STATE:
            color_value = "red"
            notify_value = 1

        elif obj.Status == NotificationEngine.UNKNOWN_STATE:
            color_value = "gray"
            notify_value = 1


        hipster.message_room(room_id=int(consul_hipchat["rooms"][roomname]), message_from="Consul",
                             message=message_template,
                             notify=notify_value,
                             color=color_value)

def notify_slack(obj, message_template,common_notifiers,consul_slack):
    common_slack_rooms = common_notifiers


    # Use slack library to use for notifications requires api_token and
    # url
    slacker = Slacker(consul_slack["api_token"])

    for roomname in common_slack_rooms:

        slacker.chat.post_message(consul_slack["rooms"][roomname],message_template,"Consul")


def notify_mailgun(obj, message_template,common_notifiers,consul_mailgun):
    common_mailgun_teams = common_notifiers


    api_endpoint = "https://api.mailgun.net/v2/{domain}/messages".format(domain=consul_mailgun["mailgun_domain"])
    auth_tuple=('api', consul_mailgun["api_token"])

    for teamname in common_mailgun_teams:

        requests.post(api_endpoint,
                      auth=auth_tuple,
                      data={'from':consul_mailgun["from"],
                            'to':consul_mailgun["teams"][teamname],
                            'subject': 'Consul Alert',
                            'text': message_template})



def notify_email(obj,message_template,common_notifiers,consul_email):
    common_email_teams = common_notifiers

    server = smtplib.SMTP(consul_email["mail_domain_address"])

    if consul_email["username"] and consul_email["password"]:
        server.login(consul_email["username"],consul_email["password"])

    from_address = consul_email["from"]
    subject = "Consul Alert"

    for teamname in common_email_teams:

        body = string.join((
            "From: %s" % from_address,
            "To: %s" % ', '.join(teamname),
            "Subject: %s" % subject ,
            "",
            message_template
            ), "\r\n")

        server.sendmail(from_address,teamname,body)

    server.quit()