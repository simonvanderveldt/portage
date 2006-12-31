# portage: news management code
# Copyright 2006 Gentoo Foundation
# Distributed under the terms of the GNU General Public License v2
# $Id$

from portage_const import PRIVATE_PATH, INCREMENTALS, PROFILE_PATH
from portage import config

import os, re

class NewsManager(object):
	"""
	This object manages GLEP 42 style news items.  It will cache news items
	that have previously shown up and notify users when there are relevant news
	items that apply to their packages that the user has not previously read.
	
	Creating a news manager requires:
	root - the value of /, can be changed via $ROOT in the environment.
	NEWS_PATH - path to news items; usually $REPODIR/metadata/news
	UNREAD_PATH - path to the news.repoid.unread file; this helps us track news items
	
	"""

	TIMESTAMP_FILE = "news-timestamp"

	def __init__( self, root, NEWS_PATH, UNREAD_PATH ):
		self.NEWS_PATH = NEWS_PATH
		self.UNREAD_PATH = UNREAD_PATH
		self.TIMESTAMP_PATH = os.path.join( root, PRIVATE_PATH, NewsManager.TIMESTAMP_FILE )
		self.target_root = root

		self.config = portage.config( config_root = os.environ.get("PORTAGE_CONFIGROOT", "/"),
				target_root = root, incrementals = INCREMENTALS)
		self.vdb = portage.vardbapi( settings = self.config, root = root,
			vartree = portage.vartree( root = root, settings = self.config ) )
		self.portdb = portage.portdbapi( porttree_root = root, mysettings = self.config )

	def updateNewsItems( self, repoid ):
		"""
		Figure out which news items from NEWS_PATH are both unread and relevant to
		the user (according to the GLEP 42 standards of relevancy).  Then add these
		items into the news.repoid.unread file.
		"""
		
		repos = self.portdb.getRepositories()
		if repoid not in repos:
			raise ValueError("Invalid repoID: %s" % repoid)

		timestamp = os.stat(self.TIMESTAMP_PATH).st_mtime
		path = os.path.join( repoid, self.NEWS_PATH )
		news = os.listdir( path )
		updates = []
		for item in news:
			try:
				tmp = NewsItem( item, timestamp )				
			except ValueError:
				continue

			if tmp.isRelevant( profile=os.readlink(PROFILE_PATH), keywords=config, vdb=self.vdb):
				updates.append( tmp )
		
		unread_file = open( os.path.join( UNREAD_PATH, "news."+ repoid +".unread" ), "a" )
		for item in updates:
			unread_file.write( item.path + "\n" )

		close(unread_file)

	def getUnreadItems( self, repoid, update=False ):
		"""
		Determine if there are unread relevant items in news.repoid.unread.
		If there are unread items return their number.
		If update is specified, updateNewsItems( repoid ) will be called to
		check for new items.
		"""
		
		if update:
			self.updateNewsItems( repoid )

		unreadfile = os.path.join( UNREAD_PATH, "news."+ repoid +".unread" )

		if os.path.exists( unreadfile ):
			unread = open( unreadfile ).readlines()
			if len(unread):
				return len(unread)

class NewsItem(object):
	"""
	This class encapsulates a GLEP 42 style news item.
	It's purpose is to wrap parsing of these news items such that portage can determine
	whether a particular item is 'relevant' or not.  This requires parsing the item
	and determining 'relevancy restrictions'; these include "Display if Installed" or
	"display if arch: x86" and so forth.

	Creation of a news item involves passing in the path to the particular news item.

	"""
	
	installedRE = re.compile("Display-If-Installed:(.*)\n")
	profileRE = re.compile("Display-If-Profile:(.*)\n")
	keywordRE = re.compile("Display-If-Keyword:(.*)\n")

	def __init__( self, path, cache_mtime = 0 ):
		""" 
		For a given news item we only want if it path is a file and it's 
		mtime is newer than the cache'd timestamp.
		"""
		if not os.path.isFile( path ):
			raise ValueError
		if not os.stat( path ).st_mtime > cache_mtime:
			raise ValueError
		self.path = path

	def isRelevant( self, vardb, config, profile ):
		"""
		This function takes a dict of keyword arguments; one should pass in any
		objects need to do to lookups (like what keywords we are on, what profile,
		and a vardb so we can look at installed packages).
		Each restriction will pluck out the items that are required for it to match
		or raise a ValueError exception if the required object is not present.
		"""

		if not len(self.restrictions):
			return True # no restrictions to match means everyone should see it
		
		kwargs = { 'vardb' : vardb,
			   'config' : config,
			   'profile' : profile }

		for restriction in self.restrictions:
			if restriction.checkRestriction( kwargs ):
				return True
			
		return False # No restrictions were met; thus we aren't relevant :(

	def parse( self ):
		lines = open(self.path).readlines()
		self.restrictions = []
		for line in lines:
			#Optimization to ignore regex matchines on lines that
			#will never match
			if not line.startswith("D"):
				continue
			match = installedRE.match( line )
			if match:
				self.restrictions.append( 
					DisplayInstalledRestriction( match.groups()[0] ) )
				continue
			match = profileRE.match( line )
			if match:
				self.restrictions.append(
					DisplayProfileRestriction( match.groups()[0] ) )
				continue
			match = keywordRE.match( line )
			if match:
				self.restrictions.append(
					DisplayKeywordRestriction( match.groups()[0] ) )
				continue

	def __getattr__( self, attr ):
		if attr == "restrictions" and not self.restrictions:
			self.parse()
		return self.restrictions

class DisplayRestriction(object):
	"""
	A base restriction object representing a restriction of display.
	news items may have 'relevancy restrictions' preventing them from
	being important.  In this case we need a manner of figuring out if
	a particular item is relevant or not.  If any of it's restrictions
	are met, then it is displayed
	"""

	def checkRestriction( self, **kwargs ):
		raise NotImplementedError("Derived class should over-ride this method")

class DisplayProfileRestriction(DisplayRestriction):
	"""
	A profile restriction where a particular item shall only be displayed
	if the user is running a specific profile.
	"""

	def __init__( self, profile ):
		self.profile = profile

	def checkRestriction( self, **kwargs ):
		if self.profile == kwargs['profile']:
			return True
		return False

class DisplayKeywordRestriction(DisplayRestriction):
	"""
	A keyword restriction where a particular item shall only be displayed
	if the user is running a specific keyword.
	"""

	def __init__( self, keyword ):
		self.keyword = keyword

	def checkRestriction( self, **kwargs ):
		if kwargs['config']["ARCH"] == self.keyword:
			return True
		return False

class DisplayInstalledRestriction(DisplayRestriction):
	"""
	An Installation restriction where a particular item shall only be displayed
	if the user has that item installed.
	"""
	
	def __init__( self, cpv ):
		self.cpv = cpv

	def checkRestriction( self, **kwargs ):
		vdb = kwargs['vardb']
		if vdb.match( cpv ):
			return True
		return False
