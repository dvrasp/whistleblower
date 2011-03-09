# -*- coding: utf-8 -*-

import mechanize
from mechanize import Link
from ClientForm import HTMLForm as Form
import cookielib
import threading, random, time, re
import logging
import _elementtidy

import urllib2, urlparse
import time

class DeadEnd(Exception):
    def __init__(self, url):
        Exception.__init__(self)
        self.url = url

class WebRobot(threading.Thread):    
    def __init__(self, options, start_url=None):
        super(WebRobot, self).__init__()
        #threading.Thread.__init__(self)
        self.options = options
        self.browser = mechanize.Browser()
        cj = cookielib.LWPCookieJar()
        if options.cookie and start_url:
            name, value = map(lambda s:s.strip(),
                              options.cookie.split("="))
            domain = urlparse.urlparse(start_url).netloc
            ck = cookielib.Cookie(version=0, name=name, value=value,
                                  port=None, port_specified=False,
                                  domain=domain,
                                  domain_specified=False,
                                  domain_initial_dot=False,
                                  path='/', path_specified=True,
                                  secure=False, expires=None, discard=True,
                                  comment=None, comment_url=None,
                                  rest={'HttpOnly': None}, rfc2109=False)
            cj.set_cookie(ck)
        self.browser.set_cookiejar(cj)

        if start_url:
            self.go(start_url)

        self._pick_history = []
        self.response_times = {}

    def add_response_time(self, dt, url):
        self.response_times[url] = dt

    def _add_pick_history(self, item):
        self._pick_history.append(item)

    def _has_pick_history(self, item):
        if isinstance(item, Link):
            for i in filter(lambda i: isinstance(i, Link), self._pick_history):
                if i.url == item.url: return True
        elif isinstance(item, Form):
            for i in filter(lambda i: isinstance(i, Form), self._pick_history):
                if i.action == item.action: return True

    def _random_pick(self):
        links = []
        if self.options.follow_links:
            try: links = list(self.browser.links())
            except: pass
        forms = []
        if self.options.use_forms:
            try: forms = list(self.browser.forms())
            except: pass

        while links or forms:
            link_or_form = random.choice(links+forms)
            if self.options.once and self._has_pick_history(link_or_form):
                try: links.remove(link_or_form)
                except Exception, e:
                    ## print e
                    pass
                try: forms.remove(link_or_form)
                except: pass
                continue
            else:
                self._add_pick_history(link_or_form)
                return link_or_form
        raise DeadEnd(self.browser.geturl())

    def _follow_link(self, link):
        logging.debug("Visiting: %s" % (link.url))
        t = time.time()
        self._response = self.browser.follow_link(link)
        dt = time.time() - t
        logging.info("Link: %s (%.2fs)" % (link.url, dt))
        self.add_response_time(dt, link.url)

    def _use_form(self, form):
        t = time.time()
        self.browser.select_form(form)
        self._response = self.browser.submit()
        dt = time.time() - t
        logging.info("Form: %s (%.2fs)" % (form.action, dt))
        self.add_response_time(dt, form.action)

    def random_surf(self):
        link_or_form = self._random_pick()
        from IPython import Shell
        Shell.IPShellEmbed()()
        if isinstance(link_or_form, Link):
            self._follow_link(link_or_form)
        elif isinstance(link_or_form, Form):
            self._use_form(link_or_form)

    def go(self, url):
        self._response = self.browser.open(url)

    def run(self):
        count = 0
        self.visited_urls = {}
        while True:
            try:
                self.random_surf()
            except DeadEnd:
                logging.debug("Going back from: %s" % self.browser.geturl())
                try:
                    self.browser.back()
                except mechanize.BrowserStateError:
                    break
            except KeyboardInterrupt:
                break
            except Exception, e:
                logging.error(e)
                break
            count += 1
            if self.options.max_count is not None \
                   and count > self.options.max_count:
                break
        print id(self)
        print "Total pages crawled:", count
        print "Average response time: %.2f" % (
            1.0*sum(self.response_times.values())/len(self.response_times))
        t = self.response_times.items()
        t.sort(lambda a,b: cmp(a[1], b[1]))
        print "Slowest urls: \n - "+ "\n - ".join(
            ["%s (%.2fs)" % (url, dt)
             for (url, dt) in reversed(t[-4:])])
        return True

class WhistleBlower(WebRobot):
    MEDIA_EXTENSIONS = ["png", "jpg", "gif", "pdf", "avi"]

    def _check_link(self, link):
        if re.match(r".*\.(%s)$" % "|".join(self.MEDIA_EXTENSIONS), link.url):
            logging.debug("Media: %s" % (link))
            #if not self.options.check_media. ... TODO
            return False
        if link.url.startswith("http://"):
            logging.info("External link: %s" % (link))
            return False            
        if link.url.startswith("mailto:"):
            logging.warning("Email address: %s" % (link))
            return False            
        if link.url.startswith("javascript:"):
            logging.debug("Javascript address: %s" % (link))
            return False            
        if re.match("[a-z]+:.*", link.url):
            logging.warning("Unkown protocol: %s" % (link))
            return False
        if link.url.startswith("#"):
            if not self.options.ignore_dash_links:
                logging.warning("Dash link: %s" % (link))
            return False
        return True

    def _check_form(self, form):
        if form.action.startswith("http://"):
            logging.warning("External form action: %s" % (unicode(form).split("\n")[0]))
            
        return True

    def _check_page_elementtidy(self):
        page = self._response.read()
        self._response.seek(0)        
        xhtml, log = _elementtidy.fixup(page)
        return log
    
    def _check_page_w3c(self):

        # wait 1 second before the next request - be nice with the validator
        time.sleep(1)
        resp= {}
        url = self.browser.geturl()
        url = url.strip()
        request_url = "http://qa-dev.w3.org/wmvs/HEAD/check?uri="+url
        logging.debug("Querying %s" % request_url)
        class Head(urllib2.Request):
            def get_method(self):
                return "HEAD"

        response = urllib2.urlopen(Head(request_url))
        if response.headers.get('x-w3c-validator-status', "Abort")=="Abort":
            return "Abort"
        resp = response.headers
        return "Status: %s Errors: %s Warnings: %s" % (resp.get('x-w3c-validator-status', "n/a"), resp.get('x-w3c-validator-errors', "n/a"), resp.get('x-w3c-validator-warnings', "n/a"))
##         try:
##             resp, content = h.request(urlrequest, "HEAD")
##             if resp['x-w3c-validator-status'] == "Abort":
##                 print url, "FAIL"
##             else:
##                 print url, resp['x-w3c-validator-status'], resp['x-w3c-validator-errors'], resp['x-w3c-validator-warnings']
##         except:
##             pass
        
        return log

    def check_page(self):
        mapping = {
            'elementtidy':self._check_page_elementtidy,
            'w3c':self._check_page_w3c,
            }
        if self.options.html_validator in mapping:
            try:
                log = mapping[self.options.html_validator]()
                if log:
                    logging.warning("Check result for %s:\n%s" % (
                        self.browser.geturl(),
                        log.strip()))
            except Exception, e:
                logging.warning("Exception while checking html: %s" % e)
        

    def random_surf(self):
        while True:
            self.check_page()
            link_or_form = self._random_pick()
            if isinstance(link_or_form, Link):
                link = link_or_form
                if not self._check_link(link):
                    continue
                try:
                    self._follow_link(link)
                    break
                except Exception, e:
                    logging.error("Error on page %s: %s" % (link.url, e))
                    self.browser.back()

            elif isinstance(link_or_form, Form):
                form = link_or_form
                if not self._check_form(form):
                    continue                
                try:
                    self._use_form(form)
                    break
                except Exception, e:
                    logging.error("Error with form %s: %s" % (form.action, e))
                    self.browser.back()
        time.sleep(self.options.surf_timer)

                 
def main():
    from optparse import OptionParser

    parser = OptionParser()
    parser.add_option("-q", "--quiet",
                      action="store_false", dest="verbose", default=True,
                      help="print many status messages to stdout")
    parser.add_option("--silent",
                      action="store_true", dest="silent", default=False,
                      help="output as least as possible")
    parser.add_option("-d", "--debug",
                      action="store_true", dest="debug", default=False,
                      help="don't print status messages to stdout")
    parser.add_option("-t", "--timer", type="float",
                      dest="surf_timer", default=0,
                      help="time between requests")
    parser.add_option("-c", "--max-count", type="float",
                      dest="max_count", default=None,
                      help="max number of page loads")
    parser.add_option("--check-dash", action="store_true",
                      dest="ignore_dash_links", default=True,
                      help="report # links")
    parser.add_option("--forms", action="store_true",
                      dest="use_forms", default=False,
                      help="use forms")
    parser.add_option("--links", action="store_true",
                      dest="follow_links", default=True,
                      help="follow links")
    parser.add_option("--html", action="store",
                      dest="html_validator", default="no",
                      help="html validation method (use no to disable)")
    parser.add_option("--cookie", action="store",
                      dest="cookie", default=None,
                      help="cookie (name=value)")
    parser.add_option("-o", "--once", action="store_true",
                      dest="once", default=True,
                      help="visit only once")
    parser.add_option("--threads", action="store", type="int",
                      default=1, dest="threads",
                      help="bots to run in parallel")
    parser.add_option("--stress", action="store_const",
                      const="stress", default=None, dest="preset",
                      help="default parameters for load test")
    parser.add_option("--heavy", action="store_const",
                      const="heavy", default=None, dest="preset",
                      help="default parameters for load test")

    (options, args) = parser.parse_args()


    if options.preset=="stress":
        options.threads = 10
        options.max_count = 5
        options.silent = True
        options.html_validator = "no"
        options.use_forms = True
    elif options.preset=="heavy":
        options.threads = 50
        options.max_count = 20
        options.silent = True
        options.html_validator = "no"
        options.use_forms = True

    if options.silent:
        logging.basicConfig(level=logging.FATAL)
    elif options.debug:
        logging.basicConfig(level=logging.DEBUG)
    elif options.verbose:
        logging.basicConfig(level=logging.INFO)
    else:
        logging.basicConfig(level=logging.WARNING)
        
    for url in args:
        if options.threads>1:
            for i in range(options.threads):
                robot = WhistleBlower(options, url)
                robot.start()
            while threading.activeCount()>1:
                time.sleep(1)
        else:
            robot = WhistleBlower(options, url)
            robot.run()

            

if __name__=="__main__":
    main()
