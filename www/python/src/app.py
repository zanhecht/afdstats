# -*- coding: utf-8 -*-

import pymysql
import sys
import os
import traceback
import urllib.parse
from urllib.request import urlopen
import re
import datetime
import time
import html

# Constants
MAX_LIMIT = 500
STATS_RESULTS = ["k", "d", "sk", "sd", "m", "r", "t", "u", "nc"]
STATS_VOTES = STATS_RESULTS[:-1]
VOTE_TYPES = [
	"Keep",
	"Delete",
	"Speedy Keep",
	"Speedy Delete",
	"Merge",
	"Redirect",
	"Transwiki",
	"Userfy",
]
FOOTER = """<footer>Bugs, suggestions, questions?
Contact the <a href="https://toolsadmin.wikimedia.org/tools/id/afdstats">maintainers</a>
at <a href="https://en.wikipedia.org/wiki/Wikipedia_talk:AfD_stats">Wikipedia talk:AfD stats</a>. • 
<a href="https://gitlab.wikimedia.org/toolforge-repos/afdstats" title="afdstats on Wikimedia GitLab">Source code</a></footer>"""

# TODO: Provide link to usersearch.py that will show all AfD edits during the time period that this search covers


def app(environ, start_response):
	# Produce 404 error if not accessed at afdstats.py
	if environ.get("PATH_INFO", "/").lstrip("/") != "afdstats.py":
		start_response("404 Not Found", [("Content-Type", "text/plain")])
		return [b"404 Not Found"]

	# initialize variables
	matchstats = [0, 0, 0]  # matches, non-matches, no consensus
	stats = {}
	votetypes = VOTE_TYPES.copy()
	for v in STATS_VOTES:
		for r in STATS_RESULTS:
			stats[v + r] = 0
	for v in votetypes:
		stats[v] = 0

	output = [
		"""<!doctype html>
<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8"/>
<title>AfD Stats - Results</title>
<link rel="stylesheet" type="text/css" href="/afdstats.css">
<link rel="icon" type="image/x-icon" href="/favicon.ico">
</head>
<body>
<div style="width:875px;">
<a href='/'><small>&larr;New search</small></a>"""
	]

	try:
		starttime = time.time()

		##################Validate input
		# form = cgi.FieldStorage()
		form = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
		username = (
			urllib.parse.unquote_plus(form.get("name", "")).replace("_", " ").strip()
		)
		if username == "":
			return errorout(
				start_response,
				output,
				f"No username entered.<!--QUERY_STRING: {environ.get('QUERY_STRING', '')}-->",
			)
		username = username[0].capitalize() + username[1:]
		altusername = (
			urllib.parse.unquote_plus(form.get("altname", "")).replace("_", " ").strip()
		)
		startdate = str(form.get("startdate", ""))
		nomsonly = (
			True if form.get("nomsonly", "").lower() in ["1", "true", "yes"] else False
		)
		undetermined = (
			True if form.get("undetermined", "").lower() in ["1", "true", "yes"] else False
		)
		if undetermined is True:
			votetypes.append("UNDETERMINED")
			stats["UNDETERMINED"] = 0
		try:
			maxsearch = min(MAX_LIMIT, int(form["max"][0]))
		except Exception:
			maxsearch = 200

		##################Query database
		db = pymysql.connect(
			db="enwiki_p",
			host="enwiki.web.db.svc.wikimedia.cloud",
			read_default_file=os.path.expanduser("~/replica.my.cnf"),
		)
		cursor = db.cursor()

		try:
			if (
				len(startdate) == 8
				and int(startdate) > 20000000
				and int(startdate) < 20300000
			):
				startdatestr = " AND rev_timestamp<=" + startdate + "235959"
			else:
				startdatestr = ""
		except (TypeError, ValueError):
			startdatestr = ""

		if nomsonly:
			cursor.execute(
				'SELECT page_title FROM revision_userindex JOIN page ON rev_page=page_id JOIN actor_revision ON actor_id=rev_actor WHERE actor_name=%s AND page_namespace=4 AND page_title LIKE "Articles_for_deletion%%" AND NOT page_title LIKE "Articles_for_deletion/Log/%%" AND rev_parent_id=0'
				+ startdatestr
				+ " ORDER BY rev_timestamp DESC;",
				(username,),
			)
		else:
			cursor.execute(
				'SELECT DISTINCT page_title FROM revision_userindex JOIN page ON rev_page=page_id JOIN actor_revision ON actor_id=rev_actor WHERE actor_name=%s AND page_namespace=4 AND page_title LIKE "Articles_for_deletion%%" AND NOT page_title LIKE "Articles_for_deletion/Log/%%"'
				+ startdatestr
				+ " ORDER BY rev_timestamp DESC;",
				(username,),
			)
		results = cursor.fetchall()

		output.append(f"<h1>AfD Statistics for User:{html.escape(username)}</h1>")

		if len(results) == 0:
			return errorout(
				start_response,
				output,
				"""No AFDs found. This user may not exist.
Note that if the user's username does not appear in the wikitext of their signature,
you may need to specify an alternate name.""",
			)

		output.append(
			"""<p>These statistics were compiled by an automated process,
and may contain errors or omissions due to the wide variety of styles with which people cast votes at AfD.
Any result fields which contain "UNDETERMINED" were not able to be parsed, and should be examined manually.</p>
<h2>Vote totals</h2>"""
		)

		if startdate:
			datestr = datetime.datetime.strptime(startdate, "%Y%m%d").strftime(
				"%b %d %Y"
			)
			output.append(
				f"Total number of unique AfD pages edited by {username} (from {datestr} and earlier): {str(len(results))}<br>"
			)
		else:
			output.append(
				f"Total number of unique AfD pages edited by {username}: {str(len(results))}<br>"
			)

		if len(results) > maxsearch:
			output.append(
				f"Only the last {str(maxsearch)} AfD pages were analyzed.<br>"
			)

		##################Analyze results
		pages = results[: min(maxsearch, len(results))]
		if len(pages) <= 50:
			alldata = APIpagedata(pages)
			if isinstance(alldata, str):
				return errorout(start_response, output, alldata)
		else:
			alldata = {}
			for i in range(0, len(pages), 50):
				newdata = APIpagedata(pages[i : min(i + 50, len(pages))])
				if isinstance(newdata, str):
					return errorout(start_response, output, newdata)
				alldata = alldata | newdata

		tablelist = []
		novotes = 0

		output.append(
			"""<small>
<a href="javascript:void(0);" onClick="if(document.getElementById('noVote').style.display === 'none') {document.getElementById('noVote').style.display = 'block';this.innerHTML='Hide pages without detected votes';} else {document.getElementById('noVote').style.display = 'none';this.innerHTML='Show pages without detected votes';}">
Show pages without detected votes
</a>
</small>
<ul id="noVote" style="display: none">"""
		)

		for entry in pages:
			try:
				page = entry[0].decode()

				# "data" means the full page text
				raw_data = alldata["Wikipedia:" + page.replace("_", " ")]
				data = html.unescape(raw_data.replace("\n", "\\n")).replace("\\n", "\n")
				data = re.sub(
					"<(s|strike|del)>.*?</(s|strike|del)>",
					"",
					data,
					flags=re.IGNORECASE | re.DOTALL,
				)

				# We don't want to include the closing statement while finding votes
				header_index = data.find("==")
				if header_index > -1:
					votes_data = data[header_index:]
				else:
					votes_data = data
				votes = re.findall(
					"'{3}?.*?'{3}?.*?(?:(?:\{\{unsigned.*?\}\})|(?:class=\"autosigned\"))?(?:\[\[[Uu]ser.*?\]\].*?\(UTC\))",
					votes_data,
					flags=re.IGNORECASE,
				)
				result_data = data[: max(header_index, data.find("(UTC)"))]
				result = findresults(result_data)
				dupvotes = []
				deletionreviews = findDRV(data[:header_index], page)

				def find_user_idx(vote):
					possible_min_user_idx = vote.rfind("[[User")
					return (
						possible_min_user_idx
						if possible_min_user_idx >= 0
						else vote.rfind("[[user")
					)

				def find_voter_match(vote):
					return re.match(
						"\[\[User.*?:(.*?)(?:\||(?:\]\]))",
						vote[find_user_idx(vote) :],
						flags=re.IGNORECASE,
					)

				firsteditor = DBfirsteditor(page, cursor)
				is_nominator = False
				if (firsteditor[0].lower() == username.lower()) or (
					firsteditor[0].lower() == altusername.lower()
				):
					is_nominator = True

				for vote in votes:
					try:
						votermatch = find_voter_match(vote)
						if votermatch is None:
							continue
						voter = votermatch.group(1).strip()

						# Sometimes, a "#top" will sneak in, so remove it
						if voter.endswith("#top"):
							voter = voter[:-4]
						if "dev" in form and form["dev"][0].lower() in [
							"1",
							"true",
							"yes",
						]:
							output.append(f"<pre>{page}, {voter}, {vote}</pre>")

						# Underscores are turned into spaces by MediaWiki title processing
						voter = voter.replace("_", " ")

						# Check if the vote was made by the user we're counting votes for
						if (
							voter.lower() == username.lower()
							or voter.lower() == altusername.lower()
						):
							votetype = parsevote(vote[3 : vote.find("'", 3)])
							if votetype is None:
								continue
							if (votetype == "UNDETERMINED") and (
								(undetermined is False) or (is_nominator is True)
							):
								continue
							timematch = re.search("(\d{2}:\d{2}, .*?) \(UTC\)", vote)
							if timematch is None:
								votetime = ""
							else:
								votetime = parsetime(timematch.group(1))
							dupvotes.append(
								(page, votetype, votetime, result, 0, deletionreviews)
							)
					except Exception as err:
						# output.append(f"<br>ERROR: {str(err)} ({html.escape(traceback.format_exc())})") #debug
						continue
				if len(dupvotes) < 1:
					if is_nominator:  # user is nominator
						tablelist.append(
							(page, "Delete", firsteditor[1], result, 1, deletionreviews)
						)
						stats = updatestats(stats, "Delete", result)
					else:
						closermatch = find_voter_match(result_data) or ""
						if isinstance(closermatch, re.Match):
							closermatch = f" (closer: {closermatch.group(1).strip()})"

						output.append(
							f"<li><a href = 'https://en.wikipedia.org/wiki/Wikipedia:{urllib.parse.quote(page)}'>{page}</a>{closermatch}</li>"
						)
						novotes += 1
				elif len(dupvotes) > 1:
					ch = len(dupvotes) - 1
					tablelist.append(dupvotes[ch])
					stats = updatestats(stats, dupvotes[ch][1], dupvotes[ch][3])
				else:
					tablelist.append(dupvotes[0])
					stats = updatestats(stats, dupvotes[0][1], dupvotes[0][3])
			except Exception as err:
				# output.append(f"<br>ERROR: {str(err)} ({html.escape(traceback.format_exc())})") #debug
				continue
		db.close()
		output.append("</ul>")
		##################Print results tables
		totalvotes = 0
		for i in votetypes:
			totalvotes += stats[i]
		if totalvotes > 0:
			output.append("<ul>")
			for i in votetypes:
				output.append(
					f"<li>{i} votes: {str(stats[i])} ({str(round((100.0 * stats[i]) / totalvotes, 1))}%)</li>"
				)
			output.append("</ul>")
			if novotes:
				output.append(
					f"The remaining {str(novotes)} pages had no discernible vote by this user."
				)
			output.append(
				"""<br>
<h2>Voting matrix</h2>
<p>This table compares the user's votes to the way the AfD eventually closed.
The only AFDs included in this matrix are those that have already closed,
where both the vote and result could be reliably determined.
Results are across the top, and the user's votes down the side.
Green cells indicate "matches", meaning that the user's vote matched (or closely resembled) the way the AfD eventually closed,
whereas red cells indicate that the vote and the end result did not match.</p>
</div>
<table border=1 style="float:left;" class="matrix">
<thead>
<tr>
<th colspan=2 rowspan=2></th>
<th colspan=9>Results</th>
</tr>
<tr>"""
			)
			for i in STATS_RESULTS:
				output.append(f"<th>{i.upper()}</th>")
			output.append("</tr>\n</thead>\n<tbody>\n<tr><th rowspan=9>Votes</th></tr>")
			for vv in STATS_VOTES:
				output.append(f"<tr>\n<th>{vv.upper()}</th>")
				for rr in STATS_RESULTS:
					output.append(
						matrixmatch(stats, vv, rr) + str(stats[vv + rr]) + "</td>"
					)
				output.append("</tr>")
			output.append(
				"""</tbody>
</table>
<br><div style="float:left;padding:20px;">
<small>Abbreviation key:
<br>K = Keep
<br>D = Delete
<br>SK = Speedy Keep
<br>SD = Speedy Delete
<br>M = Merge
<br>R = Redirect
<br>T = Transwiki
<br>U = Userfy/Draftify
<br>NC = No Consensus</small></div>
<div style="clear:both;"></div><br><br>
<div style="width:875px;">"""
			)

			afds_output = ["<h2>Individual AFDs</h2>"]
			if len(tablelist) > 0 and tablelist[-1][2]:
				afds_output.append(
					f'<a href="afdstats.py?name={username.replace(" ", "_")}&max={str(maxsearch)}&startdate={datefmt(tablelist[-1][2])}&altname={altusername}&undetermined={str(undetermined)}"><small>Next {str(maxsearch)} AfDs &rarr;</small></a><br>'
				)
			afds_output.append("</div>")
			afds_output.append(
				"""<table>
<thead>
<tr>
<th scope="col">Page</th>
<th scope="col">Vote date</th>
<th scope="col">Vote</th>
<th scope="col">Result</th>
</tr>
</thead>
<tbody>"""
			)

			for i in tablelist:
				afds_output.append("<tr>")
				afds_output.append(
					f"<td>{link(i[0])}</td>\n<td>{i[2]}</td>\n<td>{i[1]}{' (Nom)' if i[4] == 1 else ''}</td>"
				)
				matchstats, matchcell = match(matchstats, i[1], i[3], i[5])
				afds_output.append(matchcell)
				afds_output.append("</tr>")
			afds_output.append("</tbody>\n</table>")
			afds_output.append('<div style="width:875px;">')
			afds_output.append(
				f'<a href="afdstats.py?name={username.replace(" ", "_")}&max={str(maxsearch)}&startdate={datefmt(tablelist[-1][2])}&altname={altusername}&undetermined={str(undetermined)}">'
			)
			afds_output.append(
				f"<small>Next {str(maxsearch)} AFDs &rarr;</small></a><br><br>"
			)

			total_votes = sum(matchstats)
			if total_votes > 0:
				output.append(
					"Number of AFDs where vote matched result (green cells): {} ({:.1%})<br>".format(
						matchstats[0], float(matchstats[0]) / total_votes
					)
				)
				output.append(
					"Number of AFDs where vote didn't match result (red cells): {} ({:.1%})<br>".format(
						matchstats[1], float(matchstats[1]) / total_votes
					)
				)
				output.append(
					'Number of AfD\'s where result was "No Consensus" (yellow cells): {} ({:.1%})<br>\n'.format(
						matchstats[2], float(matchstats[2]) / total_votes
					)
				)
				if total_votes != matchstats[2]:
					output.append(
						'Without considering "No Consensus" results, <b>{:.1%} of AFDs were matches</b> and {:.1%} of AFDs were not.'.format(
							float(matchstats[0]) / (total_votes - matchstats[2]),
							float(matchstats[1]) / (total_votes - matchstats[2]),
						)
					)
			output.append("\n".join(afds_output))
		else:
			output.append("<br><br>No votes found.")

		elapsed = str(round(time.time() - starttime, 2))
		output.append(f"<small>Elapsed time: {elapsed} seconds.</small><br>")
		output.append(FOOTER)
		output.append(
			"""<a href="/"><small>&larr;New search</small></a>
</div>
</body>
</html>"""
		)
		start_response("200 OK", [("Content-Type", "text/html")])
		return ["\n".join(output).encode("utf-8")]

	except SystemExit:
		sys.exit(0)
	except Exception as err:
		return errorout(
			start_response,
			output,
			f"{html.escape(str(err))}<br>{html.escape(traceback.format_exc())}<br>Fatal error.",
		)


def parsevote(v):
	v = v.lower()
	if "comment" in v:
		return None
	elif "note" in v:
		return None
	elif "merge" in v:
		return "Merge"
	elif "redirect" in v:
		return "Redirect"
	elif "speedy keep" in v:
		return "Speedy Keep"
	elif "speedy delet" in v:
		return "Speedy Delete"
	elif "keep" in v:
		return "Keep"
	elif "delete" in v:
		return "Delete"
	elif "transwiki" in v:
		return "Transwiki"
	elif (
		("userfy" in v)
		or ("userfi" in v)
		or ("incubat" in v)
		or ("draftify" in v)
		or ("draftifi" in v)
	):
		return "Userfy"
	# elif ("withdraw" in v):
	# return "Speedy Keep"
	else:
		return "UNDETERMINED"


def parsetime(t):
	tm = re.search("\d{2}:\d{2}, (\d{1,2}) ([A-Za-z]*) (\d{4})", t)
	if tm is None:
		return ""
	else:
		return tm.group(2) + " " + tm.group(1) + ", " + tm.group(3)


def findresults(thepage):  # Parse through the text of an AfD to find how it was closed
	resultsearch = re.search(
		"The result (?:of the debate )?was(?:.*?\n?.*?)(?:'{3}?)(.*?)(?:'{3}?)",
		thepage,
		flags=re.IGNORECASE,
	)
	if resultsearch is None:
		if (
			"The following discussion is an archived debate of the proposed deletion of the article below"
			in thepage
			or "This page is an archive of the proposed deletion of the article below."
			in thepage
			or "'''This page is no longer live.'''" in thepage
		):
			return "UNDETERMINED"
		else:
			return "Not closed yet"
	else:
		result = resultsearch.group(1).lower()
		if "no consensus" in result:
			return "No Consensus"
		elif "merge" in result:
			return "Merge"
		elif "redirect" in result:
			return "Redirect"
		elif (
			("speedy keep" in result)
			or ("speedily kept" in result)
			or ("speedily keep" in result)
			or ("snow keep" in result)
			or ("snowball keep" in result)
			or ("speedy close" in result)
		):
			return "Speedy Keep"
		elif (
			"speedy delet" in result
			or "speedily deleted" in result
			or "snow delete" in result
			or "snowball delete" in result
		):
			return "Speedy Delete"
		elif "keep" in result:
			return "Keep"
		elif "delete" in result:
			return "Delete"
		elif "transwiki" in result:
			return "Transwiki"
		elif (
			("userfy" in result)
			or ("userfi" in result)
			or ("incubat" in result)
			or ("draftify" in result)
			or ("draftifi" in result)
		):
			return "Userfy"
		elif "withdraw" in result:
			return "Speedy Keep"
		else:
			return "UNDETERMINED"


def findDRV(
	thepage, pagename
):  # Try to find evidence of a DRV that was opened on this AfD
	try:
		drvs = ""
		drvcounter = 0
		for drv in re.finditer(
			"(?:(?:\{\{delrev xfd)|(?:\{\{delrevafd)|(?:\{\{delrevxfd))(.*?)\}\}",
			thepage,
			flags=re.IGNORECASE,
		):
			drvdate = re.search(
				"\|date=(\d{4} \w*? \d{1,2})", drv.group(1), flags=re.IGNORECASE
			)
			if drvdate:
				drvcounter += 1
				name = re.search(
					"\|page=(.*?)(?:\||$)", drv.group(1), flags=re.IGNORECASE
				)
				if name:
					nametext = urllib.parse.quote(name.group(1))
				else:
					nametext = urllib.parse.quote(
						pagename.replace("Articles_for_deletion/", "", 1)
					)
				drvs += (
					'<a href="http://en.wikipedia.org/wiki/Wikipedia:Deletion_review/Log/'
					+ drvdate.group(1).strip().replace(" ", "_")
					+ "#"
					+ nametext
					+ '"><sup><small>['
					+ str(drvcounter)
					+ "]</small></sup></a>"
				)
		return drvs
	except Exception:
		return ""


def updatestats(stats, v, r):  # Update the stats variable for votes
	if v == "Merge":
		vv = "m"
	elif v == "Redirect":
		vv = "r"
	elif v == "Speedy Keep":
		vv = "sk"
	elif v == "Speedy Delete":
		vv = "sd"
	elif v == "Keep":
		vv = "k"
	elif v == "Delete":
		vv = "d"
	elif v == "Transwiki":
		vv = "t"
	elif v == "Userfy":
		vv = "u"
	else:
		if ("UNDETERMINED" in stats) and (v == "UNDETERMINED"):
			stats["UNDETERMINED"] += 1
		return stats
	stats[v] += 1
	if r == "Merge":
		rr = "m"
	elif r == "Redirect":
		rr = "r"
	elif r == "Speedy Keep":
		rr = "sk"
	elif r == "Speedy Delete":
		rr = "sd"
	elif r == "Keep":
		rr = "k"
	elif r == "Delete":
		rr = "d"
	elif r == "Transwiki":
		rr = "t"
	elif r == "Userfy":
		rr = "u"
	elif r == "No Consensus":
		rr = "nc"
	else:
		return stats
	stats[vv + rr] += 1
	return stats


def match(matchstats, v, r, drv):  # Update the matchstats variable
	if r == "Not closed yet":
		return matchstats, f'<td class="m">{r}{drv}</td>'
	elif r == "UNDETERMINED" or v == "UNDETERMINED":
		return matchstats, f'<td class="m">{r}{drv}</td>'
	elif r == "No Consensus":
		matchstats[2] += 1
		return matchstats, f'<td class="m">{r}{drv}</td>'
	elif v == r:
		matchstats[0] += 1
		return matchstats, f'<td class="y">{r}{drv}</td>'
	elif v == "Speedy Keep" and r == "Keep":
		matchstats[0] += 1
		return matchstats, f'<td class="y">{r}{drv}</td>'
	elif r == "Speedy Keep" and v == "Keep":
		matchstats[0] += 1
		return matchstats, f'<td class="y">{r}{drv}</td>'
	elif v == "Speedy Delete" and r == "Delete":
		matchstats[0] += 1
		return matchstats, f'<td class="y">{r}{drv}</td>'
	elif r == "Speedy Delete" and v == "Delete":
		matchstats[0] += 1
		return matchstats, f'<td class="y">{r}{drv}</td>'
	elif r == "Redirect" and v == "Delete":
		matchstats[0] += 1
		return matchstats, f'<td class="y">{r}{drv}</td>'
	elif r == "Delete" and v == "Redirect":
		matchstats[0] += 1
		return matchstats, f'<td class="y">{r}{drv}</td>'
	elif r == "Merge" and v == "Redirect":
		matchstats[0] += 1
		return matchstats, f'<td class="y">{r}{drv}</td>'
	elif r == "Redirect" and v == "Merge":
		matchstats[0] += 1
		return matchstats, f'<td class="y">{r}{drv}</td>'
	else:
		matchstats[1] += 1
		return matchstats, f'<td class="n">{r}{drv}</td>'


def matrixmatch(
	stats, v, r
):  # Returns html to color the cell of the matrix table correctly, depending on whether there is a match/non-match (red/green), or if the cell is zero/non-zero (bright/dull).
	if stats[v + r]:
		if r == "nc":
			return '<td class="mm">'
		elif v == r:
			return '<td class="yy">'
		elif v == "sk" and r == "k":
			return '<td class="yy">'
		elif v == "k" and r == "sk":
			return '<td class="yy">'
		elif v == "d" and r == "sd":
			return '<td class="yy">'
		elif v == "sd" and r == "d":
			return '<td class="yy">'
		elif v == "d" and r == "r":
			return '<td class="yy">'
		elif v == "r" and r == "d":
			return '<td class="yy">'
		elif v == "m" and r == "r":
			return '<td class="yy">'
		elif v == "r" and r == "m":
			return '<td class="yy">'
		else:
			return '<td class="nn">'
	else:
		if r == "nc":
			return '<td class="mmm">'
		elif v == r:
			return '<td class="yyy">'
		elif v == "sk" and r == "k":
			return '<td class="yyy">'
		elif v == "k" and r == "sk":
			return '<td class="yyy">'
		elif v == "d" and r == "sd":
			return '<td class="yyy">'
		elif v == "sd" and r == "d":
			return '<td class="yyy">'
		elif v == "d" and r == "r":
			return '<td class="yyy">'
		elif v == "r" and r == "d":
			return '<td class="yyy">'
		elif v == "m" and r == "r":
			return '<td class="yyy">'
		elif v == "r" and r == "m":
			return '<td class="yyy">'
		else:
			return '<td class="nnn">'


def APIpagedata(rawpagelist):  # Grabs page text for all of the AFDs using the API
	try:
		p = ""
		for page in rawpagelist:
			if page[0]:
				p += urllib.parse.quote(
					"Wikipedia:" + page[0].decode().replace("_", " ") + "|"
				)
		u = urlopen(
			"http://en.wikipedia.org/w/api.php?action=query&prop=revisions|info&rvprop=content&format=xml&titles="
			+ p[:-3]
		)
		xml = u.read()
		u.close()
		pagelist = re.findall(r"<page.*?>.*?</page>", xml.decode(), re.DOTALL)
		pagedict = {}
		for i in pagelist:
			try:
				pagename = re.search(r"<page.*?title=\"(.*?)\"", i).group(1)
				text = re.search(
					r'<rev.*?xml:space="preserve">(.*?)</rev>', i, re.DOTALL
				).group(1)
				if re.search('<page.*?redirect="".*?>', i):  # AfD page is a redirect
					continue
				pagedict[html.unescape(pagename)] = text
			except Exception:
				continue
		return pagedict
	except Exception as err:
		return f"Unable to fetch page data. Please try again.<!--{str(err)}-->"


def DBfirsteditor(
	p, cursor
):  # Finds the name of the user who created a particular page, using a database query.  Replaces APIfirsteditor()
	try:
		cursor.execute(
			"SELECT actor_name, rev_timestamp FROM revision JOIN page ON rev_page=page_id JOIN actor_revision ON actor_id=rev_actor WHERE rev_parent_id=0 AND page_title=%s AND page_namespace=4;",
			(p.replace(" ", "_"),),
		)
		results = cursor.fetchall()[0]
		return (
			results[0].decode(),
			datetime.datetime.strptime(results[1].decode(), "%Y%m%d%H%M%S").strftime(
				"%B %d, %Y"
			),
		)
	except Exception:
		return None


def datefmt(datestr):
	try:
		tg = re.search("([A-Za-z]*) (\d{1,2}), (\d{4})", datestr)
		if tg is None:
			return ""
		monthmap = {
			"01": "January",
			"02": "February",
			"03": "March",
			"04": "April",
			"05": "May",
			"06": "June",
			"07": "July",
			"08": "August",
			"09": "September",
			"10": "October",
			"11": "November",
			"12": "December",
		}
		month = [k for k, v in monthmap.items() if v == tg.group(1)][0]
		day = tg.group(2)
		year = tg.group(3)
		if len(day) == 1:
			day = "0" + day
		return year + month + day
	except Exception:
		return ""


def link(p):
	text = html.escape(p.replace("_", " ")[22:])
	if len(text) > 64:
		text = text[:61] + "..."
	return (
		'<a href="http://en.wikipedia.org/wiki/Wikipedia:'
		+ urllib.parse.quote(p)
		+ '">'
		+ text
		+ "</a>"
	)


def errorout(
	start_response, output, errorstr
):  # General error handler, prints error message and aborts execution.
	output.append(
		f"<p>ERROR: {errorstr}</p><p>Please <a href='http://afdstats.toolforge.org/'>try again</a>.</p>"
	)
	output.append(FOOTER)
	output.append("</div>\n</body>\n</html>")
	start_response("500 Internal Server Error", [("Content-Type", "text/html")])
	return ["\n".join(output).encode("utf-8")]
