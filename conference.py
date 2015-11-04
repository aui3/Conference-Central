#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'


from datetime import datetime
import json
import os
import time

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import urlfetch
from google.appengine.ext import ndb

from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import TeeShirtSize

from models import Conference, Session
from models import ConferenceForm, ConferenceForms, SessionForm, SessionForms
from models import ConferenceQueryForm, ConferenceQueryForms

from models import BooleanMessage
from models import FeaturedSpeakerMessage
from models import ConflictException

from google.appengine.api import taskqueue
from google.appengine.api import memcache

MEMCAHE_KEY = "FEATURED_SPEAKER"


CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)
#Request Container for getting session of a particular type within a conference
SES_TYPE_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    type=messages.StringField(2),
)
#Request container to get all sessions for a speaker 
SES_SPEAKER_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    speaker=messages.StringField(2),
)

#Request container to add session to wishlist
SESSION_WISH_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    sessionKey=messages.StringField(1),
)
#Request container to a given type of session for a given speaker
SESSION_TYPE_SPEAKER = endpoints.ResourceContainer(
    message_types.VoidMessage,
    sessionType = messages.StringField(1),
    speakerName = messages.StringField(2),
)

#Request Container for getiing the featured apeaker.
FEATURED_SPEAKER_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    speaker=messages.StringField(1),
    )
#Request container to get all sessions by a speaker in a conference
CONFERENCE_SESSION_SPEAKER = endpoints.ResourceContainer(
    message_types.VoidMessage,
    conferencewebsafekey = messages.StringField(1),
    speakerName = messages.StringField(2),
)

from settings import WEB_CLIENT_ID


import utils


EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID

DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": [ "Default", "Topic" ],
}

SESSION_DEFAULTS = {
    "highlights": "Default Highlights",
    "duration": 0,
    "speaker": "Default Speaker",
    "sessionType": "Deafault Session Type"
}

SESSION_FIELDS = {
    'HIGHLIGHTS': 'highlights',
    'SPEAKER': 'speaker',
}

OPERATORS = {
            'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!='
            }

FIELDS =    {
            'CITY': 'city',
            'TOPIC': 'topics',
            'MONTH': 'month',
            'MAX_ATTENDEES': 'maxAttendees',
            }




# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

@endpoints.api( name='conference',
                version='v1',
                allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID],
                scopes=[EMAIL_SCOPE])


class ConferenceApi(remote.Service):
    """Conference API v0.1"""

# - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf


    def _createConferenceObject(self, request):
        """Create or update Conference object, returning ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = utils.getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        # both for data model & outbound Message
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
            setattr(request, "seatsAvailable", data["maxAttendees"])

        # make Profile Key from user ID
        p_key = ndb.Key(Profile, user_id)
        # allocate new Conference ID with Profile key as parent
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        # make Conference key from ID
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference & return (modified) ConferenceForm
        Conference(**data).put()

        return request

# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf


    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if non-existent."""
        
        #make sure user is authenticated
        user = endpoints.get_current_user() 
        
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        
        # get user_id via the helper function in utils
        user_id = utils.getUserId(user) 
        #generate a p_key for this user using the user_id
        p_key = ndb.Key(Profile, user_id)

        #get the profile associated with this p_key
        profile = p_key.get()
        if not profile:
            profile = Profile(
                key = p_key,
                displayName = user.nickname(), 
                mainEmail= user.email(),
                teeShirtSize = str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put() #save profile to datastore
        

        return profile      # return Profile


    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
            prof.put()            

        # return ProfileForm
        return self._copyProfileToForm(prof)

    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q


    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException("Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous filters
                # disallow the filter if inequality was performed on a different field before
                # track the field on which the inequality operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException("Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)

    
    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='conferences/attending',
            http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser() # get user Profile
        conf_keys = [ndb.Key(urlsafe=wsck) for wsck in prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf, names[conf.organizerUserId])\
         for conf in conferences]
        )
        # - - - Registration - - - - - - - - - - - - - - - - - - - -
    @ndb.transactional(xg=True)    
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser() # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)

    
    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:                                                                                                                                                               raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(message_types.VoidMessage, ProfileForm,
            path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()

    #ProfileMiniForm is the request class and we pass the request to the _doProfile(..) method.
    @endpoints.method(ProfileMiniForm, ProfileForm,
            path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)


    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
            http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)
    
    #all conferences
    @endpoints.method(ConferenceQueryForms, ConferenceForms,
                path='queryConferences',
                http_method='POST',
                name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

         # return individual ConferenceForm object per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") \
            for conf in conferences]
        )
    
     # all conferences created by logged in user   
    @endpoints.method(CONF_GET_REQUEST, ConferenceForms,
            path='getConferencesCreated',
            http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # make profile key
        p_key = ndb.Key(Profile, utils.getUserId(user))
        # create ancestor query for this user
        conferences = Conference.query(ancestor=p_key)
        # get the user profile and display name
        prof = p_key.get()
        displayName = getattr(prof, 'displayName')
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, displayName) for conf in conferences]
        )



     #----------Sessions -----
     
    #create a session object
    def _createSessionObject(self, request):
        """Create or update Session object, returning SessionForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = utils.getUserId(user)

        if not request.sessionName:
            raise endpoints.BadRequestException("Conference 'name' field required")

       
        wsck = request.c_websafeKey
        conf = ndb.Key(urlsafe=wsck).get() # get the conference
        #check if current user is owner of conference 
        if conf.organizerUserId == user_id:


            # copy SessionForm/ProtoRPC Message into dict
            data = {field.name: getattr(request, field.name) for field in request.all_fields()}


            # convert dates and time from strings to Date and time formatted  objects 
            if data['startTime']:
                data['startTime'] = datetime.strptime(data['startTime'][:5], "%H:%M").time()
            
            if data['date']:
                data['date'] = datetime.strptime(data['date'][:10], "%Y-%m-%d").date()
           
            
            #get conference key
            c_key = ndb.Key(urlsafe=wsck)
            #auto-generate id for the session using parent as the conference key
            c_id = Session.allocate_ids(size=1, parent=c_key)[0]
            # make Session key from ID
            s_key = ndb.Key(Session, c_id, parent=c_key)
            #save the session websafe key
            data['sessionWebSafeKey'] = s_key.urlsafe()
            data['key'] = s_key
            

            # create session & return (modified) SessionForm
            Session(**data).put()

            speaker_name = data['speaker']

            #check to see if for this session, this particular speaker has more than 1 session. If so, this speaker becomes the featured speaker.
            conf_sessions = Session.query()
            # get all sessions for this speaker in this conference
            conf_sessions = conf_sessions.filter( Session.c_websafeKey == wsck)
            conf_sessions = conf_sessions.filter(Session.speaker == speaker_name)
            count = conf_sessions.count()
            print "$$$ %s", count


            #if so, add to the taskqueue to put this speaker name in memcache
            if count > 1:
                taskqueue.add(params={'speakerName' : speaker_name},
                                   url='/tasks/set_featured_speaker', method='GET')

            return request   
        else:
            raise ConflictException('Unauthorised to create this session')

    
    #set the memcache with speaker name
    @staticmethod
    def _set_speaker_cache(featured_speaker):
        print "####, %s", featured_speaker
        memcache.set("MEMCAHE_KEY",featured_speaker)




    #Create a session
    @endpoints.method(SessionForm, SessionForm, path='session',
            http_method='POST', name='createSession')
    def createSession(self, request):
        """Create new session."""
        return self._createSessionObject(request)    


    #Copy session to Form
    def _copySessionToForm(self, session):
        """Copy relevant fields from Session to SessionForm."""
        cf = SessionForm()
        
        for field in cf.all_fields():
            if hasattr(session, field.name):
                # convert Date to date string and time to time string; just copy others
                if field.name == "date":
                    setattr(cf, field.name, str(getattr(session, field.name)))
                
                elif field.name == "startTime":
                    setattr(cf, field.name, str(getattr(session, field.name)))    
                
                elif field.name == "c_websafeKey":
                    setattr(cf, field.name, getattr(session, field.name))   
                #a case for default values if no values entered
                elif getattr(session, field.name) == None:
                    setattr(cf, field.name, 'Default')    
                else:
                    setattr(cf, field.name, getattr(session, field.name))

        cf.check_initialized()
        return cf
        

    #Get all sessions in a conference
    @endpoints.method(CONF_GET_REQUEST, SessionForms,
            path='getConferenceSessions/{websafeConferenceKey}',
            http_method='GET', name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """Get list of sessions in a conference."""
        
        #web safe key of this conference
        wsck = request.websafeConferenceKey
        
        #filter using this conference web safe key for sessions.
        
        sessions = Session.query()
        sessions = sessions.filter(Session.c_websafeKey == wsck).fetch()
         
        return SessionForms(items=[self._copySessionToForm(ses) for ses in sessions])


    #Get all sessions in a conference by type
    @endpoints.method(SES_TYPE_GET_REQUEST, SessionForms,
            path='getConferenceSessionsByType/{websafeConferenceKey,type}',
            http_method='GET', name='getConferenceSessionsByType')
    def getConferenceSessionsByType(self, request):
        """Get list of sessions in a conference by type."""
        
        #web safe key of this conference
        sesType = request.type
        conf = request.websafeConferenceKey
         
        #filter using this conference web safe key for sessions.
        
        sessions = Session.query()
        sessions = sessions.filter(Session.c_websafeKey == conf)
        sessions = sessions.filter(Session.sessionType == sesType).fetch()
        
        
        return SessionForms(items=[self._copySessionToForm(ses) for ses in sessions])



    #Get all sessions by speaker
    @endpoints.method(SES_SPEAKER_GET_REQUEST, SessionForms,
            path='getSessionsBySpeaker/{speaker}',
            http_method='GET', name='getSessionsBySpeaker')
    def getSessionsBySpeaker(self, request):
        """Get list of sessions in a conference by type."""
        
        #web safe key of this conference
        speaker = request.speaker
        #c_wsck = request.websafeConferenceKey
        
 
        #filter using this conference web safe key for sessions.
        #print wsck
        sessions = Session.query()
        
        sessions = sessions.filter(Session.speaker == speaker).fetch()
        
        
        return SessionForms(items=[self._copySessionToForm(ses) for ses in sessions])        


    #add session to wishlist
    def _sessionWishList(self, request):
        """add session to wishlist"""
        retval = None
        prof = self._getProfileFromUser() # get user Profile
        

        #get url safe session key from request
        sesKey= request.sessionKey
        
        # check if user already added to wishlist
        if sesKey in prof.wishListSessionKeys:
            retval = False
            raise ConflictException(
                    "You have already added this session to your wish list")
        else:
            # add wishlist
            prof.wishListSessionKeys.append(sesKey)
            retval = True

        # write things back to the datastore & return
        prof.put()
        return BooleanMessage(data=retval)

    #add session wish list based on the url safe session key
    @endpoints.method(SESSION_WISH_REQUEST, BooleanMessage,
            path='sessionWishList/{sessionKey}',
            http_method='POST', name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """Add session to wish list."""
        return self._sessionWishList(request)    


    #get sessions in wishlist
    @endpoints.method(message_types.VoidMessage, SessionForms,
            path='getSessionsInWishList',
            http_method='POST', name='getSessionsInWishList')
    def getSessionsInWishList(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get user profile
        prof = self._getProfileFromUser() # get user Profile
        
        ses_keys = [ndb.Key(urlsafe=ses) for ses in prof.wishListSessionKeys]
        sessions = ndb.get_multi(ses_keys)
        
        
        return SessionForms(
            items=[self._copySessionToForm(ses) for ses in sessions]
        )

#Query 1
#for a patricular speaker, find particular type of sessions
    @endpoints.method(SESSION_TYPE_SPEAKER, SessionForms,
            path='sessionTypeBySpeaker/{sessionType,speakerName}',
            http_method='POST', name='sessionTypeBySpeaker')
    def sessionTypeBySpeaker(self, request):
        """Return session based on type and speaker name"""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        sesType = request.sessionType
        spkrName = request.speakerName
        sessions = Session.query()
        sessions = sessions.filter(Session.speaker == spkrName)
        sessions = sessions.filter (Session.sessionType == sesType)
        sesssions = sessions.fetch()

        # return set of SessionForma objects 
        return SessionForms(
            items=[self._copySessionToForm(ses) for ses in sessions]
        )

#Query 2
#for a conference find sessions by a speaker.

    @endpoints.method(CONFERENCE_SESSION_SPEAKER, SessionForms,
            path='allConferenceSessionsOfSpeaker/{conferencewebsafekey,speakerName}',
            http_method='POST', name='allConferenceSessionsOfSpeaker')
    def allConferenceSessionsOfSpeaker(self, request):
        """Return sessions of a speaker in a conference"""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        confwsk = request.conferencewebsafekey
        spkrName = request.speakerName
        
        #find all sessions in this conference
        confses = Session.query()
        confses = confses.filter(Session.c_websafeKey == confses)

        sessions = confses.filter(Session.speaker == spkrName)
        sessions = sessions.fetch()


        #sessions = Session.query()
        #sessions = sessions.filter(Session.speaker == spkrName)
        #sessions = sessions.filter (Session.sessionType == sesType)
        #sesssions = sessions.fetch()

        # return set of SessionForma objects 
        return SessionForms(
            items=[self._copySessionToForm(ses) for ses in sessions]
        )    

     #Task 4 Endpoint method to get the featured speaker.
    @endpoints.method(message_types.VoidMessage, FeaturedSpeakerMessage,
            path='getFeaturedSpeaker',
            http_method='GET', name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        """Get featured speaker from memcache""" 
        spkr=memcache.get("MEMCAHE_KEY")
        print "^^^ %s", spkr
        return FeaturedSpeakerMessage(data=spkr)    


        #filterplayground
        # all conferences created by logged in user   
    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='filterPlayground',
            http_method='POST', name='filterPlayground')
    def filterPlayground(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

#delete everything in users wishlist
        prof = self._getProfileFromUser() # get user Profile
        #print "******* %s" ,prof.wishListSessionKeys
        prof.wishListSessionKeys[:] = []

   
        conferences = Conference.query()
        conferences = conferences.filter(Conference.city == "London")    

        
        
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") for conf in conferences]
        )


# registers API
api = endpoints.api_server([ConferenceApi]) 
