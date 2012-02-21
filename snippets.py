import datetime
import os

# Before importing anything from appengine, set the django version we want.
from google.appengine.dist import use_library
os.environ['DJANGO_SETTINGS_MODULE'] = 'settings'
use_library('django', '1.2')

from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.ext import db

"""Snippets server.

This server runs the Khan Academy weekly snippets.  Users can
add a summary of what they did in the last week, and browse
other people's snippets.  They will also get weekly mail with
everyone's snippets in them.
"""

__author__ = 'Craig Silverstein <csilvers@khanacademy.org>'


port = os.environ['SERVER_PORT']
if port and port != '80':
    HOST_NAME = '%s:%s' % (os.environ['SERVER_NAME'], port)
else:
    HOST_NAME = os.environ['SERVER_NAME']


class User(db.Model):
    """User preferences."""
    user = db.UserProperty(auto_current_user_add=True)
    category = db.StringProperty()       # used to group snippets together
    wants_email_for = db.TextProperty()  # comma-separated list of usernames


class Snippet(db.Model):
    """Every snippet is identified by the monday of the week it goes with."""
    user = db.UserProperty(auto_current_user_add=True)
    week = db.DateProperty(required=True)      # the monday of the week
    text = db.TextProperty()
    private = db.BooleanProperty(default=False)


def _login_page(request, response):
    """Writes the login page to a response object."""
    response.out.write('<html><body>You must be logged in to use'
                       ' the snippet server.'
                       ' <a href="%s">Log in</a>.'
                       '</body></html>'
                       % users.create_login_url(request.uri))


def fill_in_missing_snippets(existing_snippets, user, today):
    """Make sure that the snippets array has a Snippet entry for every week.

    The db may have holes in it -- weeks where the user didn't write a
    snippet.  Augment the given snippets array so that it has no holes,
    by adding in default snippet entries if necessary.  Note it does
    not add these entries to the db, it just adds them to the array.

    Arguments:
       existing_snippets: a list of Snippet objects for a given user.
         The first snippet in the list is assumed to be the oldest
         snippet from that user (at least, it's where we start filling
         from).
       user: a db.User object representing the person whose snippets it is.
       today: a datetime.date object representing the current day.
         We fill up to then.  If today is wed or before, then we
         fill up to the previous week.  If it's thurs or after, we
         fill up to the current week.

    Returns:
      A new list of Snippet objects, without any holes.
    """
    no_snippet_text = '(No snippet for this week)'
    today_weekday = today.weekday()   # monday == 0, sunday == 6
    if today_weekday <= 2:            # wed or before
        end_monday = today - datetime.timedelta(today_weekday + 7)
    else:
        end_monday = today - datetime.timedelta(today_weekday)        

    if not existing_snippets:         # no snippets at all?  Just do this week
        return [Snippet(user=user, week=end_monday, text=no_snippet_text)]

    # Add a sentinel, one week past the last week we actually want.
    # We'll remove it at the end.
    existing_snippets.append(Snippet(user=user,
                                     week=end_monday + datetime.timedelta(7)))

    all_snippets = [existing_snippets[0]]   # start with the oldest snippet
    for snippet in existing_snippets[1:]:
        while snippet.week - all_snippets[-1].week > datetime.timedelta(7):
            missing_week = all_snippets[-1].week + datetime.timedelta(7)
            all_snippets.append(Snippet(user=user, week=missing_week,
                                        text=no_snippet_text))
        all_snippets.append(snippet)

    # Get rid of the sentinel we added above.
    del all_snippets[-1]

    return all_snippets


class UserPage(webapp.RequestHandler):
    def get(self):
        if not users.get_current_user():
            return _login_page(self.request, self.response)

        user_q = User.all()
        # TODO(csilvers): allow other users
        user_q.filter('user = ', users.get_current_user())
        results = user_q.fetch(1)
        if results:
            user = results[0]
        else:
            user = User(user=users.get_current_user())
            db.put(user)

        snippets_q = Snippet.all()
        snippets_q.filter('user = ', user.user)
        snippets_q.order('week')            # note this puts oldest snippet first
        snippets = snippets_q.fetch(1000)   # good for many years...

        # TODO(csilvers): allow mocking in a different day
        _TODAY = datetime.datetime.now().date() + datetime.timedelta(100) #!!
        snippets = fill_in_missing_snippets(snippets, user.user, _TODAY)
        snippets.reverse()                  # get to newest snippet first

        template_values = {
            'message': self.request.get('msg'),
            'username': user.user.nickname(),
            'snippets': snippets,
            }
        path = os.path.join(os.path.dirname(__file__), 'user_snippets.html')
        self.response.out.write(template.render(path, template_values))    


# TODO(csilvers): would like to move to an ajax model where each
# snippet has a button next to it that says 'edit', and if you click
# that it becomes a textbox with buttons saying 'save' and 'cancel'.
# 'cancel' will go back to the previous state, while 'save' will go
# back to the previous state and send an ajax request to update the
# snippet in the db.

class UpdateSnippet(webapp.RequestHandler):
    def get(self):
        if not users.get_current_user():
            return _login_page(self.request, self.response)

        # TODO(csilvers): allow other users
        user = users.get_current_user()

        week_string = self.request.get('week')
        week = datetime.datetime.strptime(week_string, '%m-%d-%Y').date()
        assert week.weekday() == 0, 'passed-in date must be a Monday'

        text = self.request.get('snippet')

        private = self.request.get('private') == 'True'

        q = Snippet.all()
        q.filter('user = ', user)
        q.filter('week = ', week)
        results = q.fetch(1)
        if results:
            results[0].text = text   # just update the snippet text
            results[0].private = private
            db.put(results[0])       # update the snippet in the db
        else:                        # add the snippet to the db
            db.put(Snippet(user=user, week=week, text=text, private=private))

        # TODO(csilvers): keep the username argument, if any
        self.redirect("/?msg=Snippet+saved")


application = webapp.WSGIApplication([('/', UserPage),
                                      ('/update_snippet', UpdateSnippet),
                                      ],
                                      debug=True)


def main():
  run_wsgi_app(application)


if __name__ == "__main__":
  main()