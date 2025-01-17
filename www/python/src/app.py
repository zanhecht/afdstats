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
APP_NAME = "afdstats.py"
MAX_LIMIT = 500
WIKI_URL = "http://en.wikipedia.org/"
FOOTER = """<footer>Bugs, suggestions, questions? Contact the
<a href="https://toolsadmin.wikimedia.org/tools/id/afdstats">maintainers</a> at
<a href="https://en.wikipedia.org/wiki/Wikipedia_talk:AfD_stats">Wikipedia talk:AfD
stats</a>. • <a href="https://gitlab.wikimedia.org/toolforge-repos/afdstats"
title="afdstats on Wikimedia GitLab">Source code</a></footer>"""

TRUES = ["1", "true", "yes"]
STATS_RESULTS = ["k", "d", "sk", "sd", "m", "r", "t", "u", "nc"]
STATS_VOTES = STATS_RESULTS[:-1]
RESULT_TYPES = [
	"Keep",
	"Delete",
	"Speedy Keep",
	"Speedy Delete",
	"Merge",
	"Redirect",
	"Transwiki",
	"Userfy",
	"No Consensus",
]
VOTE_TYPES = RESULT_TYPES[:-1]
VOTE_MAP = {
	"comment": None,
	"note": None,
	"merge": "Merge",
	"redirect": "Redirect",
	"speedy keep": "Speedy Keep",
	"speedy delet": "Speedy Delete",
	"keep": "Keep",
	"delete": "Delete",
	"transwiki": "Transwiki",
	"userf": "Userfy",
	"incubat": "Userfy",
	"draftif": "Userfy",
	# "withdraw": "Speedy Keep"
}
RESULT_MAP = {
	"no consensus": "No Consensus",
	"merge": "Merge",
	"redirect": "Redirect",
	"speedy keep": "Speedy Keep",
	"speedily keep": "Speedy Keep",
	"speedyily kept": "Speedy Keep",
	"snow keep": "Speedy Keep",
	"snowball keep": "Speedy Keep",
	"speedy close": "Speedy Keep",
	"speedy delet": "Speedy Delete",
	"speedily delet": "Speedy Delete",
	"snow delet": "Speedy Delete",
	"snowball delet": "Speedy Delete",
	"keep": "Keep",
	"delete": "Delete",
	"transwiki": "Transwiki",
	"userf": "Userfy",
	"incubat": "Userfy",
	"draftif": "Userfy",
	"withdraw": "Speedy Keep",
}
MONTH_MAP = {
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

DATE_TG_PATTERN = re.compile("([A-Za-z]*) (\d{1,2}), (\d{4})")
DRV_PATTERN = re.compile(
	"(?:(?:\{\{delrev xfd)|(?:\{\{delrevafd)|(?:\{\{delrevxfd))(.*?)\}\}",
	flags=re.IGNORECASE,
)
DRV_DATE_PATTERN = re.compile("\|date=(\d{4} \w*? \d{1,2})", flags=re.IGNORECASE)
DRV_NAME_PATTERN = re.compile("\|page=(.*?)(?:\||$)", flags=re.IGNORECASE)
PAGE_LIST_PATTERN = re.compile(r"<page.*?>.*?</page>", re.DOTALL)
PAGE_NAME_PATTERN = re.compile(r"<page.*?title=\"(.*?)\"")
PAGE_TEXT_PATTERN = re.compile(r'<rev.*?xml:space="preserve">(.*?)</rev>', re.DOTALL)
PAGE_REDIRECT_PATTERN = re.compile('<page.*?redirect="".*?>')
RESULT_PATTERN = re.compile(
	"The result (?:of the debate )?was(?:.*?\n?.*?)(?:'{3}?)(.*?)(?:'{3}?)",
	flags=re.IGNORECASE,
)
STRIKE_PATTERN = re.compile(
	"<(s|strike|del)>.*?</(s|strike|del)>",
	flags=re.IGNORECASE | re.DOTALL,
)
TIME_MATCH_PATTERN = re.compile("(\d{2}:\d{2}, .*?) \(UTC\)")
TIME_PATTERN = re.compile("\d{2}:\d{2}, (\d{1,2}) ([A-Za-z]*) (\d{4})")
VOTE_PATTERN = re.compile(
	"'{3}?.*?'{3}?.*?(?:(?:\{\{unsigned.*?\}\})|(?:class=\"autosigned\"))?"
	+ "(?:\[\[[Uu]ser.*?\]\].*?\(UTC\))",
	flags=re.IGNORECASE,
)
VOTER_MATCH_PATTERN = re.compile(
	"\[\[User.*?:(.*?)(?:\||(?:\]\]))", flags=re.IGNORECASE
)

# TODO: Provide link to usersearch.py that will show all
# AfD edits during the time period that this search covers


# uWSGI entry point
def app(environ, start_response):
	# Produce 404 error if not accessed at APP_NAME
	if environ.get("PATH_INFO", "/").lstrip("/") != APP_NAME:
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
<script>
	function toggleNV(e) {
		var wasHidden = document.getElementById('noVote').style.display === 'none';
		document.getElementById('noVote').style.display = wasHidden ? 'block' : 'none';
		e.textContent = (wasHidden ? 'Hide' : 'Show') + e.textContent.slice(4);
	}
</script>
</head>
<body>
<div style="width:875px;">
<a href='/'><small>&larr;New search</small></a>"""
	]

	try:
		starttime = time.time()

		##################Validate input
		form = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
		username = (
			urllib.parse.unquote_plus(form.get("name", [""])[0])
			.replace("_", " ")
			.strip()
		)
		if username == "":
			return errorout(
				start_response,
				output,
				f"No username entered.<!--{environ.get('QUERY_STRING', '')}-->",
			)
		username = username[0].capitalize() + username[1:]
		altusername = (
			urllib.parse.unquote_plus(form.get("altname", [""])[0])
			.replace("_", " ")
			.strip()
		)
		startdate = str(form.get("startdate", [""])[0])
		nomsonly = form.get("nomsonly", [""])[0].lower() in TRUES
		dev = form.get("dev", [""])[0].lower() in TRUES
		undetermined = form.get("undetermined", [""])[0].lower() in TRUES
		if undetermined is True:
			votetypes.append("UNDETERMINED")
			stats["UNDETERMINED"] = 0
		try:
			maxsearch = min(MAX_LIMIT, int(form["max"][0]))
		except Exception:
			maxsearch = 200

		startdatestr = ""
		try:
			if (
				len(startdate) == 8
				and int(startdate) > 20000000
				and int(startdate) < 20300000
			):
				startdatestr = f" AND rev_timestamp<={startdate}235959"
		except Exception:
			pass

		results = queryDB(startdatestr, nomsonly, username)

		output.append(f"<h1>AfD Statistics for User:{html.escape(username)}</h1>")

		if len(results) == 0:
			return errorout(
				start_response,
				output,
				"""No AfDs found. This user may not exist. Note that if the user's"
username does not appear in the wikitext of their signature, you may need to specify an
alternate name.""",
			)

		output.append(
			"""<p>These statistics were compiled by an automated process, and may"
contain errors or omissions due to the wide variety of styles with which people cast
votes at AfD. Any result fields which contain "UNDETERMINED" were not able to be parsed,
and should be examined manually.</p>
<h2>Vote totals</h2>"""
		)

		startdatestr = ""
		if startdate:
			datestr = datetime.datetime.strptime(startdate, "%Y%m%d")
			startdatestr = f" (from {datestr:'%b %d %Y'} and earlier)"
		output.append(
			"Total number of unique AfD pages edited by {}{}: {}<br>".format(
				username, startdatestr, len(results)
			)
		)

		if len(results) > maxsearch:
			output.append(f"Only the last {maxsearch} AfD pages were analyzed.<br>")

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
			"""<small><a id href="javascript:void(0);" onClick="toggleNV(this)">
Show pages without detected votes</a></small>
<ul id="noVote" style="display: none">"""
		)

		for entry in pages:
			try:
				page = entry[0].decode()

				# "data" means the full page text
				raw_data = alldata["Wikipedia:" + page.replace("_", " ")]
				data = html.unescape(raw_data.replace("\n", "\\n")).replace("\\n", "\n")
				data = STRIKE_PATTERN.sub("", data)

				# We don't want to include the closing statement while finding votes
				header_index = data.find("==")
				if header_index > -1:
					votes_data = data[header_index:]
				else:
					votes_data = data
				votes = VOTE_PATTERN.findall(votes_data)
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
					return VOTER_MATCH_PATTERN.match(vote[find_user_idx(vote) :])

				firsteditor = (
					entry[1].decode(),
					datetime.datetime.strptime(
						entry[2].decode(), "%Y%m%d%H%M%S"
					).strftime("%B %d, %Y"),
				)
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
						if dev is True:
							output.append(f"<pre>{page}, {voter}, {vote}</pre>")

						# Underscores are turned into spaces by MediaWiki
						voter = voter.replace("_", " ")

						# Check if vote was made by the user we're counting votes for
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
							timematch = TIME_MATCH_PATTERN.search(vote)
							if timematch is None:
								votetime = ""
							else:
								votetime = parsetime(timematch.group(1))
							dupvotes.append(
								(page, votetype, votetime, result, 0, deletionreviews)
							)
					except Exception as err:
						if dev is True:
							output.append(f"<br>ERROR: {str(err)}<br>")
							output.append(html.escape(traceback.format_exc()))
						continue
				if len(dupvotes) < 1:
					if is_nominator:  # user is nominator
						tablelist.append(
							(page, "Delete", firsteditor[1], result, 1, deletionreviews)
						)
						updatestats(stats, "Delete", result)
					else:
						closermatch = find_voter_match(result_data) or ""
						if isinstance(closermatch, re.Match):
							closermatch = f" (closer: {closermatch.group(1).strip()})"

						output.append(
							"<li><a href = '{}wiki/Wikipedia:{}'>{}</a>{}</li>".format(
								WIKI_URL, urllib.parse.quote(page), page, closermatch
							)
						)
						novotes += 1
				elif len(dupvotes) > 1:
					ch = len(dupvotes) - 1
					tablelist.append(dupvotes[ch])
					updatestats(stats, dupvotes[ch][1], dupvotes[ch][3])
				else:
					tablelist.append(dupvotes[0])
					updatestats(stats, dupvotes[0][1], dupvotes[0][3])
			except Exception as err:
				if dev is True:
					output.append(f"<br>ERROR: {str(err)}<br>")
					output.append(html.escape(traceback.format_exc()))
				continue
		output.append("</ul>")
		##################Print results tables
		totalvotes = 0
		for i in votetypes:
			totalvotes += stats[i]
		if totalvotes > 0:
			output.append("<ul>")
			for i in votetypes:
				output.append(
					f"<li>{i} votes: {stats[i]} ({(stats[i] / totalvotes):.1%})</li>"
				)
			output.append("</ul>")
			if novotes:
				output.append(
					f"The remaining {novotes} pages had no discernible vote by this user."
				)
			output.append(
				"""<br>
<h2>Voting matrix</h2>
<p>This table compares the user's votes to the way the AfD eventually closed.
The only AfDs included in this matrix are those that have already closed,
where both the vote and result could be reliably determined.
Results are across the top, and the user's votes down the side.
Green cells indicate "matches", meaning that the user's vote matched
(or closely resembled) the way the AfD eventually closed,
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
					output.append(f"{matrixmatch(stats, vv, rr)}{stats[vv + rr]}</td>")
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

			nextlink = ""
			if len(tablelist) > 0 and tablelist[-1][2]:
				nextlink = (
					'<a href="{}?name={}&max={}&startdate={}{}{}{}{}">'.format(
						APP_NAME,
						username.replace(" ", "_"),
						maxsearch,
						datefmt(tablelist[-1][2]),
						f"&altname={altusername}" if (altusername != "") else "",
						"&undetermined=1" if (undetermined is True) else "",
						"&nomsonly=1" if (nomsonly is True) else "",
						"&dev=1" if (dev is True) else "",
					)
					+ f"<small>Next {maxsearch} AfDs &rarr;</small></a><br>"
				)

			afd_rows = []
			for i in tablelist:
				afd_rows.append(afdrow(matchstats, i))  # update matchstats

			total_votes = sum(matchstats)
			if total_votes > 0:
				matchstrs = [
					"vote matched result (green cells)",
					"vote didn't match result (red cells)",
					'result was "No Consensus" (yellow cells)',
				]
				for i in range(3):
					output.append(
						"Number of AfDs where {}: {} ({:.1%})<br>".format(
							matchstrs[i],
							matchstats[i],
							float(matchstats[i]) / total_votes,
						)
					)
				if total_votes != matchstats[2]:
					output.append(
						'Without considering "No Consensus" results, <b>'
						+ "{:.1%} of AfDs were matches</b> and {:.1%} were not.".format(
							float(matchstats[0]) / (total_votes - matchstats[2]),
							float(matchstats[1]) / (total_votes - matchstats[2]),
						)
					)
			output.append(
				f"""<h2>Individual AfDs</h2>",
{nextlink}
</div>
<table>
<thead>
<tr>
	<th scope="col">Page</th>
	<th scope="col">Vote date</th>
	<th scope="col">Vote</th>
	<th scope="col">Result</th>
</tr>
</thead>
<tbody>
{afd_rows.join("\n")}
</tbody>
</table>
<div style="width:875px;">{nextlink}<br>"""
			)
		else:
			output.append(f"<br><br>No votes found.<!--{stats}-->")

		output.append(
			f"""<small>Elapsed time: {(time.time() - starttime):.2f} seconds.</small><br>"
{FOOTER}
<a href="/"><small>&larr;New search</small></a>
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
			f"""{html.escape(str(err))}<br>
{html.escape(traceback.format_exc())}<br>
Fatal error.""",
		)


def queryDB(startdatestr, nomsonly, username):
	##################Query database
	querystr = """SELECT {}, rev.rev_timestamp FROM revision_userindex AS rev
JOIN page ON rev.rev_page=page_id
JOIN actor_revision AS actor ON actor.actor_id=rev.rev_actor
{} WHERE actor.actor_name=%s AND page_namespace=4
AND page_title LIKE "Articles_for_deletion%%"
AND NOT page_title LIKE "Articles_for_deletion/Log/%%"
{} ORDER BY rev.rev_timestamp DESC;"""
	if nomsonly is True:
		querystr = querystr.format(
			"DISTINCT page_title, actor.actor_name",
			"",
			" AND rev.rev_parent_id=0" + startdatestr,
		)
	else:
		querystr = querystr.format(
			"page_title, first_actor.actor_name",
			"""JOIN revision_userindex AS first_rev ON first_rev.rev_page=page_id
AND first_rev.rev_parent_id=0
JOIN actor_revision AS first_actor ON first_actor.actor_id=first_rev.rev_actor""",
			startdatestr,
		)

	db = pymysql.connect(
		database="enwiki_p",
		host="enwiki.web.db.svc.wikimedia.cloud",
		read_default_file=os.path.expanduser("~/replica.my.cnf"),
	)
	with db:
		with db.cursor() as cursor:
			cursor.execute(
				querystr,
				(username,),
			)
			results = cursor.fetchall()
	return results


def parsevote(v):
	for key, vote in VOTE_MAP.items():
		if key in v.lower():
			return vote
	return "UNDETERMINED"


def parsetime(t):
	tm = TIME_PATTERN.search(t)
	if tm is None:
		return ""
	else:
		return f"{tm.group(2)} {tm.group(1)}, {tm.group(3)}"


def findresults(thepage):  # Parse through the text of an AfD to find how it was closed
	resultsearch = RESULT_PATTERN.search(thepage)
	if resultsearch is None:
		if (
			"The following discussion is an archived debate of the proposed deletion of the article below"
			in thepage
			or "This page is an archive of the proposed deletion of the article below."
			in thepage
			or "'''This page is no longer live.'''" in thepage
		):
			return "UNDETERMINED"
		return "Not closed yet"
	for key, result in RESULT_MAP.items():
		if key in resultsearch.group(1).lower():
			return result
	return "UNDETERMINED"


def findDRV(thepage, pagename):
	# Try to find evidence of a DRV that was opened on this AfD
	try:
		drvs = ""
		drvcounter = 0
		baseurl = f"{WIKI_URL}/wiki/Wikipedia:Deletion_review/Log/"
		for drv in DRV_PATTERN.finditer(thepage):
			drvdate = DRV_DATE_PATTERN.search(drv.group(1))
			if drvdate:
				drvcounter += 1
				name = DRV_NAME_PATTERN.search(drv.group(1))
				if name:
					nametext = urllib.parse.quote(name.group(1))
				else:
					nametext = urllib.parse.quote(
						pagename.replace("Articles_for_deletion/", "", 1)
					)
				drvs += '<a href="{}{}#{}"><sup><small>[{}]</small></sup></a>'.format(
					baseurl,
					drvdate.group(1).strip().replace(" ", "_"),
					nametext,
					drvcounter,
				)
		return drvs
	except Exception:
		return ""


def updatestats(stats, v, r):  # Update the stats variable for votes
	if v in VOTE_TYPES:
		vv = STATS_VOTES[VOTE_TYPES.index(v)]
	else:
		if ("UNDETERMINED" in stats) and (v == "UNDETERMINED"):
			stats["UNDETERMINED"] += 1
		return
	stats[v] += 1
	if r in RESULT_TYPES:
		rr = STATS_RESULTS[RESULT_TYPES.index(r)]
	else:
		return
	stats[vv + rr] += 1


def afdrow(matchstats, i):  # Update the matchstats variable and generate table row
	v, r, drv = i[1], i[3], i[5]
	c = "m"
	if r == "No Consensus":
		matchstats[2] += 1
	elif (
		v == r
		or ((v in ["Speedy Keep", "Keep"]) and (r in ["Speedy Keep", "Keep"]))
		or ((v in ["Speedy Delete", "Delete"]) and (r in ["Speedy Delete", "Delete"]))
		or ((v in ["Redirect", "Delete"]) and (r in ["Redirect", "Delete"]))
		or ((v in ["Redirect", "Merge"]) and (r in ["Redirect", "Merge"]))
	):
		matchstats[0] += 1
		c = "y"
	elif r != "Not closed yet" and r != "UNDETERMINED" and v != "UNDETERMINED":
		matchstats[1] += 1
		c = "n"
	return f"""<tr>
	<td>{link(i[0])}</td>
	<td>{i[2]}</td>
	<td>{v}{" (Nom)" if i[4] == 1 else ""}</td>
	<td class="{c}">{r}{drv}</td>
</tr>"""


def matrixmatch(stats, v, r):
	# Returns html to color the cell of the matrix table correctly,
	# depending on whether there is a match/non-match (red/green),
	# or if the cell is zero/non-zero (bright/dull).
	if stats[v + r]:
		if r == "nc":
			return '<td class="mm">'
		elif (
			v == r
			or (v == "sk" and r == "k")
			or (v == "k" and r == "sk")
			or (v == "d" and r == "sd")
			or (v == "sd" and r == "d")
			or (v == "d" and r == "r")
			or (v == "r" and r == "d")
			or (v == "m" and r == "r")
			or (v == "r" and r == "m")
		):
			return '<td class="yy">'
		else:
			return '<td class="nn">'
	else:
		if r == "nc":
			return '<td class="mmm">'
		elif (
			v == r
			or (v == "sk" and r == "k")
			or (v == "k" and r == "sk")
			or (v == "d" and r == "sd")
			or (v == "sd" and r == "d")
			or (v == "d" and r == "r")
			or (v == "r" and r == "d")
			or (v == "m" and r == "r")
			or (v == "r" and r == "m")
		):
			return '<td class="yyy">'
		else:
			return '<td class="nnn">'


def APIpagedata(rawpagelist):  # Grabs page text for all of the AfDs using the API
	try:
		p = ""
		for page in rawpagelist:
			if page[0]:
				p += urllib.parse.quote(
					f"Wikipedia:{page[0].decode().replace('_', ' ')}|"
				)
		u = urlopen(
			WIKI_URL
			+ "w/api.php"
			+ "?action=query&prop=revisions|info&rvprop=content&format=xml&titles="
			+ p[:-3]
		)
		xml = u.read()
		u.close()
		pagelist = PAGE_LIST_PATTERN.findall(xml.decode())
		pagedict = {}
		for i in pagelist:
			try:
				pagename = PAGE_NAME_PATTERN.search(i).group(1)
				text = PAGE_TEXT_PATTERN.search(i).group(1)
				if PAGE_REDIRECT_PATTERN.search(i):  # AfD page is a redirect
					continue
				pagedict[html.unescape(pagename)] = text
			except Exception:
				continue
		return pagedict
	except Exception as err:
		return f"Unable to fetch page data. Please try again.<!--{err}-->"


def datefmt(datestr):
	try:
		tg = DATE_TG_PATTERN.search(datestr)
		if tg is None:
			return ""
		month = [k for k, v in MONTH_MAP.items() if v == tg.group(1)][0]
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
		text = f"{text[:61]}..."
	return '<a href="{}wiki/Wikipedia:{}">{}</a>'.format(
		WIKI_URL, urllib.parse.quote(p), text
	)


def errorout(start_response, output, errorstr):
	# General error handler, prints error message and aborts execution.
	output.append(
		f"""<p>ERROR: {errorstr}</p>
<p>Please <a href='http://afdstats.toolforge.org/'>try again</a>.</p>"""
	)
	output.append(FOOTER)
	output.append("</div>\n</body>\n</html>")
	start_response("500 Internal Server Error", [("Content-Type", "text/html")])
	return ["\n".join(output).encode("utf-8")]
