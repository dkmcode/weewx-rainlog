from __future__ import with_statement
import Queue
import datetime
import hashlib
import httplib
import platform
import re
import socket
import sys
import syslog
import threading
import time
import urllib
import urllib2
from cookielib import CookieJar

import weedb
import weeutil.weeutil
import weewx.engine
from weeutil.weeutil import to_int, to_float, to_bool, timestamp_to_string, accumulateLeaves
import weewx.manager
import weewx.units

import sys
from weewx.restx import StdRESTful
from weewx.restx import RESTThread
from weewx.restx import FailedPost
from weewx.restx import BadLogin
from weewx.restx import ConnectError
from weewx.restx import SendError
import time

def logmsg(dst, msg):
    syslog.syslog(dst, 'rainlog: %s' % msg)

def logdbg(msg):
    logmsg(syslog.LOG_DEBUG, msg)

def loginf(msg):
    logmsg(syslog.LOG_INFO, msg)

def logcrt(msg):
    logmsg(syslog.LOG_CRIT, msg)

def logerr(msg):
    logmsg(syslog.LOG_ERR, msg)

class StdRainlog(StdRESTful):
    """Upload data to Rainlog 
    http://rainlog.org
    """

    def __init__(self, engine, config_dict):
        super(StdRainlog, self).__init__(engine, config_dict)

        self.protocol_name = 'Rainlog'
        
        try:
            site_dict = accumulateLeaves(config_dict['StdRESTful']['Rainlog'],
                                         max_level=1)
            site_dict['username']
            site_dict['password']
            site_dict['WEEWX_ROOT'] = config_dict['WEEWX_ROOT']
        except KeyError, e:
            logdbg("rainlog: %s: "
                   "Data will not be posted: Missing option %s" %
                   (self.protocol_name , e) )
            return

        site_dict['manager_dict'] = weewx.manager.get_manager_dict(
            config_dict['DataBindings'],
            config_dict['Databases'],
            'wx_binding')

        self.loop_queue = Queue.Queue()
        self.loop_thread = RainlogThread(self.loop_queue,
                                         protocol_name=self.protocol_name,
                                         **site_dict)
        self.loop_thread.start()
        self.bind(weewx.NEW_LOOP_PACKET, self.new_loop_packet)

        #self.archive_queue = Queue.Queue()
        #self.archive_thread = RainlogThread(self.archive_queue, **site_dict)
        #self.archive_thread.start()
        #self.bind(weewx.NEW_ARCHIVE_RECORD, self.new_archive_record)
            
    def new_loop_packet(self, event):
        """Puts new LOOP packets in the loop queue"""
        self.loop_queue.put(event.packet)
 
    def new_archive_record(self, event):
        pass

class RainlogThread(RESTThread):

    def __init__(self, queue, username, password,
                 manager_dict,
                 WEEWX_ROOT,
                 lastpath='archive/rainlog.last',
                 protocol_name='Rainlog',
                 skip_upload=False,
                 post_interval=None, max_backlog=1, stale=None,
                 log_success=True, log_failure=True, 
                 timeout=60, max_tries=3, retry_wait=5):

        super(RainlogThread, self).__init__(queue,
                                           protocol_name=protocol_name,
                                           manager_dict=manager_dict,
                                           post_interval=post_interval,
                                           max_backlog=max_backlog,
                                           stale=stale,
                                           log_success=log_success,
                                           log_failure=log_failure,
                                           timeout=timeout,
                                           max_tries=max_tries,
                                           retry_wait=retry_wait)

        self.protocol_name = protocol_name
        self.username = username
        self.password = password

        if (lastpath[0] == '/' ):
            self.lastfile = lastpath
        else:
            self.lastfile = WEEWX_ROOT + lastpath

        try:
            with open(self.lastfile,"r") as lastfile:
                self.lastupdate = to_float(lastfile.read())
            lastfile.close()
        except IOError as e:
            self.create_lastfile()
            self.lastupdate = 0.0

    def create_lastfile(self):
        try:
            with open(self.lastfile,"w") as lastfile:
                lastfile.write('0.0')
            lastfile.close()
        except IOError as e:
            logerr( "%s: Create lastfile: %s" % (self.protocol_name, e) )
            sys.exit()

    def skip_this_post(self, time_ts):
        endupdate=time.mktime(time.strptime(time.strftime('%a %b %d 07:00:00 %Y')))
        if (endupdate == self.lastupdate) | \
                (to_float(time.time()) < endupdate):
            return True
        else:
            return False

    def process_record(self, record, dbmanager):
        loginf("Posting")
        endupdate=time.mktime(time.strptime(time.strftime('%a %b %d 07:00:00 %Y')))
        #if (endupdate == self.lastupdate) | \
        #        (to_float(time.time()) < endupdate):
        #    return

        beginupdate = endupdate - 86400
        endupdatest = time.localtime(endupdate)

        rainamt = dbmanager.getSql("SELECT SUM(rain) FROM archive WHERE dateTime > %s and dateTime <= %s " % ( beginupdate , endupdate))[0]
        packetdelay=str(time.time() - record['dateTime'])


        loginf("lastupdate=%d thisupdate=%d current=%d delay=%s %f" % (self.lastupdate, endupdate, time.time(), packetdelay, rainamt ) )



#########
# get session ID
########
        cj = CookieJar()
        opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cj))
        opener.addheaders = [('User-agent', "weewx/%s" % weewx.__version__)]

        sessidurl = 'http://rainlog.org/usprn/html/admin/index.jsp'

        sessidvalues = {'content' : 'rain.jsp',
                        'mode' : 'add' }

        sessiddata = urllib.urlencode(sessidvalues)
        

        #self.check_response = self.check_getsessid
        try:
            response = self.post_with_retries(sessidurl,sessiddata, opener)
        except Exception as e:
            logerr("%s: Get session ID: %s" % (self.protocol_name, e))
            raise  FailedPost("Failed to get session ID")
            return


############
# Login
############
        loginurl = 'http://rainlog.org/usprn/html/main/j_security_check'
        loginvalues = {'j_username' : self.username,
                       'j_password' : self.password,
                       'hasError' : 'true',
                       'Button2' : 'Login'}
        logindata = urllib.urlencode(loginvalues)

        #self.check_response = self.check_login
        try:
            logresp = self.post_with_retries(loginurl,logindata, opener)
        except Exception as e:
            logerr("%s: Login error: %s" % (self.protocol_name, e))
            return

        login_page = logresp.read()

#check for "Invalid login attempt. Please try again."
        try:
            login_page.index('Invalid')
            logerr("%s: Login Failed: check rainlog username and password" % self.protocol_name )
            raise BadLogin("Rainlog login failed")
            return
        except ValueError:
            pass

        ssearch = 'userId" VALUE="'
        esearch = '">'
        try:
            s=login_page.index(ssearch)
            s = s+len(ssearch)
            e = login_page.index(esearch,s)
        except ValueError:
            logerr("%s: Faild to get userid" % self.protocol_name)
            return

        userid = login_page[s:e]

############
# Submit
############
        quality = 'Good'

        readingdate = time.strftime('%m/%d/%Y',endupdatest)
        readingdatem = time.strftime('%m/%d/%Y+%H:%M:%S',endupdatest)
        hr = time.strftime('%H',endupdatest)
        minute = time.strftime('%M',endupdatest)
        submiturl = 'http://rainlog.org/usprn/html/admin/rain.jsp'
        submitvalues = {'quality' : quality,
                        'rain_amt' : rainamt,
                        'snow_depth' : '',
                        'snow_accumulation' : '',
                        'reading_type' : 'total',
                        'date_reading_tmp' : readingdate,
                        'drHour' : hr,
                        'drMinute' : minute,
                        'comments' : '',
                        'mode' : 'insert',
                        'id' : '0',
                        'userId' : userid,
                        'status' : 'Active',
                        'date_reading_m' :  readingdatem,
                        'page' : 'null',
                        'form_type' : 'single'}
        submitdata = urllib.urlencode(submitvalues)
        loginf(submitdata)

        #self.check_response = self.check_submit
        try:
            submitresp = self.post_with_retries(submiturl,submitdata, opener)
        except Exception as e:
            logerr("%s: Submit error: %s" % (self.protocol_name, e))
            return

        submit_page = submitresp.read()

        with open(self.lastfile,"w") as lastfile:
            lastfile.write( str(endupdate) )
        self.lastupdate = endupdate
        lastfile.close()

    # def check_getsessid(self, response):
    #     loginf("check getsessid")

    # def check_login(self, response):
    #     loginf("check login")

    # def check_submit(self, response):
    #     loginf("check submit")



    def post_with_retries(self, url, data = None, opener = None):
        """Post a request, retrying if necessary
        
        Attempts to post the request object up to max_tries times. 
        Catches a set of generic exceptions.
        
        opener: An instance of urllib2.build_opener
        """

        # Retry up to max_tries times:
        for _count in range(self.max_tries):
            try:
                # Do a single post. The function post_request() can be
                # specialized by a RESTful service to catch any unusual
                # exceptions.
                _response = self.post_request(url, data, opener)
                if _response.code == 200:
                    # No exception thrown and we got a good response code, but
                    # we're still not done.  Some protocols encode a bad
                    # station ID or password in the return message.
                    # Give any interested protocols a chance to examine it.
                    # This must also be inside the try block because some
                    # implementations defer hitting the socket until the
                    # response is used.
                    self.check_response(_response)
                    # Does not seem to be an error. We're done.
                    return _response
                else:
                    # We got a bad response code. Log it and try again.
                    logdbg("%s: Failed upload attempt %d: Code %s" % 
                           (self.protocol_name, _count+1, _response.code))
            except (urllib2.URLError, socket.error, httplib.BadStatusLine, httplib.IncompleteRead), e:
                # An exception was thrown. Log it and go around for another try
                logdbg("%s: Failed upload attempt %d: Exception %s" % 
                              (self.protocol_name, _count+1, e))
            time.sleep(self.retry_wait)
        else:
            # This is executed only if the loop terminates normally, meaning
            # the upload failed max_tries times. Raise an exception. Caller
            # can decide what to do with it.
            raise FailedPost("Failed upload after %d tries" % (self.max_tries,))


    def post_request(self, url, data = None, opener = None):
        """Post a request object. This version does not catch any HTTP
        exceptions.
        
        Specializing versions can can catch any unusual exceptions that might
        get raised by their protocol.
        """
        try:
            # Python 2.5 and earlier do not have a "timeout" parameter.
            # Including one could cause a TypeError exception. Be prepared
            # to catch it.
            if opener is None:
                _response = urllib2.urlopen(url, data, timeout=self.timeout)
            else:
                _response = opener.open(url, data, self.timeout)
        except TypeError:
            # Must be Python 2.5 or early. Use a simple, unadorned request
            if opener is None:
                _response = urllib2.urlopen(url, data)
            else:
                _response = opener.open(url, data)
        return _response
