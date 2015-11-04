App Engine application for the Udacity tFSND Project 4 - Conference Central.

## Products
- [App Engine][1]

## Language
- [Python][2]

## APIs
- [Google Cloud Endpoints][3]

##
Developed an endpoints API, that lets the users to add sessions to conference and  run certain queries on sessions 

##

## Setup Instructions
1. Update the value of `application` in `app.yaml` to the app ID you
   have registered in the App Engine admin console and would like to use to host
   your instance of this sample.
1. Update the values at the top of `settings.py` to
   reflect the respective client IDs you have registered in the
   [Developer Console][4].
1. Update the value of CLIENT_ID in `static/js/app.js` to the Web client ID

1. Run the app with the devserver using `dev_appserver.py DIR`, and ensure it's running by visiting
   your local server's address (by default [localhost:8080][5].)
1. Generate your client library(ies) with [the endpoints tool][6].
1. Deploy your application.


[1]: https://developers.google.com/appengine
[2]: http://python.org
[3]: https://developers.google.com/appengine/docs/python/endpoints/
[4]: https://console.developers.google.com/
[5]: https://localhost:8080/
[6]: https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool

The application can be accessed by going to [Conference Central](http://hello-conference-central.appspot.com)

The endpoints can be accessed at [Conference Central Endpoints](https://hello-conference-central.appspot.com/_ah/api/explorer)

<b>Task 1:</b>
+ getConferenceSessions(websafeConferenceKey) -- Given a conference, return all sessions, takes as input the websafe conference key
- getConferenceSessionsByType(websafeConferenceKey, typeOfSession) Given a conference, return all sessions of a specified type (eg lecture, keynote, workshop)
* getSessionsBySpeaker(speaker) -- Given a speaker, return all sessions given by this particular speaker, across all conferences
+ createSession(SessionForm, websafeConferenceKey) -- open only to the organizer of the conference, date entered in format 2016-01-01

<b>Session Model </b>

In my Session Model I have made the following design choices:
+ Speaker name is represented as a string with the model
- The websafekey of the conference that this session belongs to is stored as a string within the model
* The model also stores the websafekey for the session and this key is used to add a session in a wishlist.

<b>Wish List</b>
Session wishlist is implemented so that the websafe session keys of sessions in a profile's wishlist are stored as a list in the Profile Model. 

<b>Additional Queries</b>
Two following session queries are programmed:
+
- For a patricular speaker, find particular type of sessions
+ For a conference find sessions by a speaker.

<b>Let’s say that you don't like workshops and you don't like sessions after 7 pm. How would you handle a query for all non-workshop sessions before 7 pm? What is the problem for implementing this query? What ways to solve it did you think of?</b>

The not equal to filter (!=) actually performs two queries. One where the inequlity filter is replaced with greater than (>) and second where the inequlaity filter is replaced with a less than (<) filter. A query that has one not equal filter (two inequlity filters on the same prperty) can not have another inequlaity filter. 

So for our query, after filtering for session not equal to workshop (two inequlity filters) we can not have additional inequality filters to check for workshops time greater than (after) 7 pm.

[Source](https://cloud.google.com/appengine/docs/python/datastore/queries#Python_Property_filters)

The above query is not possible because it would involve two inequality queries on properties. This is violating the restriction that an inequality filter can be aplied to atmost one property.

<b>Proposed Solution</b>
Build a composite index on type of session and time of session. 

<b>Task 4</b>
getFeaturedSpeaker() :Using push task queues to set memcache entry for featured speaker. When a new session is created for a given conference, I check whether for this conference, does this speaker have more than one sessions. If so, I add a task in the queue to set in the memcache this speaker as the featured speaker. So the featured speaker will be set on the most recent session added and obviously the conference for this session is added. The getFeaturedSpeaker() endpoint function simply reads the memcache and retrieves the name of the featured speaker.
