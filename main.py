from google.appengine.api import app_identity
from conference import ConferenceApi
import webapp2

class SetFeaturedSpeaker(webapp2.RequestHandler):
    def get(self):
        """Set featured speaker in the memcache"""
        ConferenceApi._set_speaker_cache(self.request.get('speakerName'))

        


app = webapp2.WSGIApplication([
    ('/tasks/set_featured_speaker', SetFeaturedSpeaker),
], debug=True)