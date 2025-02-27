import cached_session
from bs4 import BeautifulSoup, NavigableString
import re
import pathlib
import sys
import subprocess

FORCE_FETCH = False

api_root_url = "http://wslwebservices.leg.wa.gov"

requests = cached_session.CustomCachedSession("bill_cache")

rcw_pattern = re.compile("RCW  ([0-9A-Z]+)\\.([0-9A-Z]+)\\.([0-9A-Z]+)")
chapter_pattern = re.compile("([0-9A-Z]+)\\.([0-9A-Z]+) RCW")

short_committee_status_to_acronym = {
    "H": {
        "Approps": "APP",
        "Cap Budget": "CB",
        "Children, Yout": "CYF",
        "Children, Youth": "CYF",
        "Civil R & Judi": "CRJ",
        "Coll & Wkf Dev": "CWD",
        "Comm & Econ De": "CED",
        "Comm & Econ Dev": "CED",
        "Commerce & Gam": "COG",
        "Commerce & Gami": "COG",
        "ConsPro&Bus": "CPB",
        "Education": "ED",
        "Env & Energy": "ENVI",
        "Finance": "FIN",
        "HC/Wellness": "HCW",
        "Hous, Human Sv": "HHSV",
        "Hous, Human Svc": "HHSV",
        "Labor & Workpl": "LAWS",
        "Labor & Workpla": "LAWS",
        "Local Govt": "LG",
        "Public Safety": "PS",
        "RDev, Ag&NR": "RDAN",
        "State Govt & T": "SGOV",
        "State Govt & Tr": "SGOV",
        "Transportation": "TR"
    },
    "S": {
        "Ag/Water/Natur": "AWNP",
        "Ag/Water/Natura": "AWNP",
        "Behavioral Hea": "BH",
        "Behavioral Heal": "BH",
        "Business, Fina": "BFST",
        "Business, Finan": "BFST",
        "EL/K-12": "EDU",
        "Environment, E": "ENET",
        "Environment, En": "ENET",
        "Health & Long": "HLTC",
        "Health & Long T": "HLTC",
        "Higher Ed & Wo": "HEWD",
        "Housing & Loca": "HLG",
        "Housing & Local": "HLG",
        "Human Svcs, Re": "HSRR",
        "Human Svcs, Ree": "HSRR",
        "Labor, Comm &": "LCTA",
        "Labor, Comm & T": "LCTA",
        "Law & Justice": "LAW",
        "State Govt & E": "SGE",
        "State Govt & El": "SGE",
        "Transportation": "TRAN",
        "Ways & Means": "WM",
    }
}

def get_citation(xml):
    t = xml.TitleNumber
    if t:
        t = t.text
    c = xml.ChapterNumber
    if c:
        c = c.text
    s = xml.SectionNumber
    if s:
        s = s.text
    return (t, c, s)

AMEND_INCLUDE = ("add", )
AMEND_EXCLUDE = ("strike", "strikemarkright", "strikemarknone")

# Prep all of the file locations.
title_folders = {}
chapter_files = {}
for p in pathlib.Path(sys.argv[1]).iterdir():
    if p.is_dir():
        if p.name == ".git":
            continue
        title = p.name.split("_", maxsplit=1)[0].lstrip("0")
        title_folders[title] = p
        chapter_files[title] = {}
        for chapter_file in p.iterdir():
            if chapter_file.name == "README.md":
                continue
            chapter = chapter_file.name.split("_", maxsplit=1)[0].split(".")[1].lstrip("0")
            chapter_files[title][chapter] = chapter_file

section_pattern = re.compile("\\(([a-z]+|[0-9]+)\\)")

sections_through_pattern = re.compile("([0-9]+) through ([0-9]+)")
sections_pattern = re.compile("([0-9]+)")

# Keep track of what paths have already been amended. This makes sure we copy
# the original back in place for the original amendment. Without it, we'll add
# multiple copies of amendments over time.
amended = set()

def format_lists(paragraph):
    new_paragraph = []
    for line in paragraph:
        line = line.strip()
        current_line = []
        last_end = 0
        for result in section_pattern.finditer(line):
            if result.start() != last_end:
                break
            if last_end > 0:
                current_line.append(" [Empty]")
                new_paragraph.append("".join(current_line))
                new_paragraph.append("")
                current_line = []
            last_end = result.end()
            group = result.group(1)
            if group.isnumeric():
                current_line.append(group + ".")
            elif group[0] == "i" and last_group != "h":
                current_line.append("    " * 2 + group + ".")
            else:
                current_line.append("    " * 1 + group + ".")
            last_group = group
        current_line.append(line[last_end:])
        new_paragraph.append("".join(current_line))
        new_paragraph.append("")
    return new_paragraph

def section_path(citation):
    try:
        f = chapter_files[citation[0]][citation[1].lstrip("0")]
        return f
    except KeyError:
        return None

def amend_section(revision_path, citation, section_citation, new_text):
    f = section_path(citation)
    if f is None:
        return None
    new = revision_path / f
    if new.exists() and new in amended:
        existing_text = new.read_text().split("\n")
    else:
        new.parent.mkdir(parents=True, exist_ok=True)
        existing_text = f.read_text().split("\n")
        amended.add(new)
    new_chapter = []
    in_section = False
    section_header = "## " + ".".join(citation)
    for line in existing_text:
        if line.startswith("##"):
            in_section = line.startswith(section_header)
            if in_section:
                new_chapter.append("## **" + line[2:].strip() + "**")
                new_chapter.extend(format_lists(new_text))
        if not in_section:
            new_chapter.append(line)
        elif line.startswith("[ "):
            new_chapter.append("[ **" + section_citation + ";** " + line[2:])

    new.write_text("\n".join(new_chapter))
    return new

def delete_section(revision_path, citation, section_citation):
    f = section_path(citation)
    if f is None:
        return None
    new = revision_path / f
    if new.exists() and new in amended:
        existing_text = new.read_text().split("\n")
    else:
        new.parent.mkdir(parents=True, exist_ok=True)
        existing_text = f.read_text().split("\n")
        amended.add(new)
    new_chapter = []
    in_section = False
    section_header = "## " + ".".join(citation)
    # TODO: Leave deletion trail
    for line in existing_text:
        if line.startswith("##"):
            in_section = line.startswith(section_header)
        if not in_section:
            new_chapter.append(line)

    new.write_text("\n".join(new_chapter))
    return new

def add_section(revision_path, citation, section_citation, new_text):
    f = section_path(citation)
    if f is None:
        return None
    new = revision_path / f
    if new.exists() and new in amended:
        existing_text = new.read_text().split("\n")
    else:
        new.parent.mkdir(parents=True, exist_ok=True)
        existing_text = f.read_text().split("\n")
        amended.add(new)

    new_chapter = []
    for line in existing_text:
        new_chapter.append(line)
    new_chapter.append(f"## **{citation[0]}.{citation[1]}.XXX - TBD**")
    new_chapter.append("**")
    new_chapter.extend(format_lists(new_text))
    new_chapter.append("")
    new_chapter.append("[ " + section_citation + "; ]**")
    new_chapter.append("")

    new.write_text("\n".join(new_chapter))
    return new

def new_chapter(revision_path, citation, chapter_name, contents):
    print("new chapter", citation, chapter_name)
    f = title_folders[citation[0]] / (chapter_name.replace(" ", "_") + ".md")
    chapter = [
        f"= {citation[0]}.XXX - {chapter_name}",
        ":toc:",
        ""
    ]
    for section_citation, section_number, contents in contents:
        chapter.append(f"== {citation[0]}.XXX.{section_number} - TBD")
        chapter.extend(format_lists(contents))
        chapter.append("")
        chapter.append("[ " + section_citation + "; ]")
        chapter.append("")
    new = revision_path / f
    new.parent.mkdir(parents=True, exist_ok=True)
    new.write_text("\n".join(chapter))

bills_path = pathlib.Path("bill/")
all_bills_readme = ["# All Bills by Biennium"]

for start_year in range(2021, 2023, 2):
    biennium = f"{start_year:4d}-{(start_year+1) % 100:02d}"
    print(biennium)

    biennium_readme = ["# " + biennium, ""]
    biennium_path = bills_path / biennium

    all_bills_readme.append(f"* [{biennium}]({str(biennium_path.relative_to(bills_path))}/)")

    bills_by_status = {"committee": {}, "passed": []}

    url = api_root_url + f"/SponsorService.asmx/GetRequesters?biennium={biennium}"
    requesters = requests.get(url)
    requesters = BeautifulSoup(requesters.text, "xml")
    count = 0
    for info in requesters.find_all("LegislativeEntity"):
        count += 1
    print(count, "requesters")

    sponsors_by_id = {}

    url = api_root_url + f"/SponsorService.asmx/GetSponsors?biennium={biennium}"
    sponsors = requests.get(url)
    sponsors = BeautifulSoup(sponsors.text, "xml")
    count = 0
    for info in sponsors.find_all("Member"):
        # if count == 0:
        #     print(info)
        sponsors_by_id[info.Id.text] = info
        count += 1
    print(count, "sponsors")

    url = api_root_url + f"/CommitteeService.asmx/GetCommittees?biennium={biennium}"
    print(url)
    committees = requests.get(url)
    committees = BeautifulSoup(committees.text, "xml")
    last_agency = None
    committees_by_agency = {}
    # TODO: Table of contents
    for committee in committees.find_all("Committee"):
        agency = committee.Agency.text
        name = committee.Name.text
        acronym = committee.Acronym.text
        print(agency, name, acronym)
        if last_agency != agency:
            # biennium_readme.append(f"[{agency}](#{agency.lower()})")
            committees_by_agency[agency] = []
        last_agency = agency
        committees_by_agency[agency].append((acronym, name))
        slug = name.lower().replace(" ", "-")
        # biennium_readme.append(f"* [{name}](#{slug})")

    url = api_root_url + f"/LegislativeDocumentService.asmx/GetAllDocumentsByClass?biennium={biennium}&documentClass=Bills"
    print(url)
    all_bill_docs = BeautifulSoup(requests.get(url, force_fetch=FORCE_FETCH).text, "xml")
    docs_by_number = {}
    count = 0
    for doc in all_bill_docs.find_all("LegislativeDocument"):
        bill_number = doc.BillId.text
        if not bill_number:
            continue
        bill_number = bill_number.split()[-1]
        if bill_number not in docs_by_number:
            docs_by_number[bill_number] = []
        docs_by_number[bill_number].append(doc)
        count += 1
    print(count, "bill docs")

    url = api_root_url + f"/LegislationService.asmx/GetLegislationByYear?year={start_year}"
    legislationOdd = requests.get(url, force_fetch=FORCE_FETCH)
    legislationOdd = BeautifulSoup(legislationOdd.text, "xml")
    url = api_root_url + f"/LegislationService.asmx/GetLegislationByYear?year={start_year+1}"
    legislationEven = requests.get(url, force_fetch=FORCE_FETCH)
    legislationEven = BeautifulSoup(legislationEven.text, "xml")
    count = 0
    bills_by_sponsor = {}
    bills_by_number = {}
    sponsor_by_bill_number = {}
    for info in legislationOdd.find_all("LegislationInfo") + legislationEven.find_all("LegislationInfo"):
        bill_number = info.BillNumber.text
        bill_id = info.BillId.text

        # Skip bills that may have been from the previous year.
        if bill_number in bills_by_number:
            continue

        # Skip resolutions
        if bill_id.startswith("HR") or bill_id.startswith("SR") or bill_id.startswith("HJR"):
            continue
        # Skip governor appointments
        if bill_id.startswith("SGA"):
            continue
        # Skip memorials
        if bill_id.startswith("SJM"):
            continue

        bills_url = api_root_url + f"/LegislationService.asmx/GetLegislation?biennium={biennium}&billNumber={bill_number}"
        if bill_number == "1007":
            print(bills_url)
        bills = requests.get(bills_url, force_fetch=FORCE_FETCH)
        bills = BeautifulSoup(bills.text, "xml")
        full_info = None
        for bill in bills.find_all("Legislation"):
            full_info = bill
            sponsor_id = full_info.PrimeSponsorID.text
            if bill_number not in docs_by_number:
                print(bill_number, "missing doc")
            if sponsor_id not in sponsors_by_id:
                print(sponsor_id, "missing sponsor for bill", bill_id)
            if sponsor_id not in bills_by_sponsor:
                bills_by_sponsor[sponsor_id] = {}
            if bill_number not in bills_by_sponsor[sponsor_id]:
                bills_by_sponsor[sponsor_id][bill_number] = []
            bills_by_sponsor[sponsor_id][bill_number].append(full_info)
            if bill_number not in bills_by_number:
                bills_by_number[bill_number] = []
            bills_by_number[bill_number].append(full_info)
        sponsor_by_bill_number[bill_number] = sponsor_id

        count += 1
        if count % 100 == 0:
            print("loaded", count)
    print(count, "legislation")
    print()

    amendments_by_bill_number = {}

    for year in (start_year, start_year + 1):
        url = api_root_url + f"/AmendmentService.asmx/GetAmendments?year={year}"
        amendments = requests.get(url)
        amendments = BeautifulSoup(amendments.text, "xml")
        count = 0
        for amendment in amendments.find_all("Amendment"):
            bill_number = amendment.BillNumber.text
            if bill_number not in amendments_by_bill_number:
                amendments_by_bill_number[bill_number] = []
            amendments_by_bill_number[bill_number].append(amendment)
            # print(amendment.Name.text, )
            count += 1
        print(count, "amendments")

    # for sponsor in bills_by_sponsor:
    #     sponsor_info = sponsors_by_id[sponsor]
    #     if sponsor_info.LastName.text != "Ryu":
    #         continue
    #     print(sponsor_info)
    # sys.exit()
    #     sponsor_name = sponsor_info.Name.text
    #     sponsor_email = sponsor_info.Email.text.lower().replace("@leg.wa.gov", "@wa-law.org")
    #     gitlab_user = sponsor_info.Email.text.lower().split("@")[0]
    #     for bill_number in bills_by_sponsor[sponsor]:
    bill_link_by_number = {}
    for i, bill_number in enumerate(bills_by_number):
            # if bill_number != "1000":
            #     continue
            sponsor = sponsor_by_bill_number[bill_number]
            status = ""
            bill = None
            bill_id = None
            for b in bills_by_sponsor[sponsor][bill_number]:
                # Find the shortest billId because we don't want engrossed or substitutes.
                if bill_id is None or len(b.BillId.text) < len(bill_id):
                    bill_id = b.BillId.text
                if b.Active.text != "true":
                    continue
                # print(b.CurrentStatus.Status.text, b.CurrentStatus.HistoryLine.text)
                status = b.CurrentStatus.Status.text
                bill = b

            if bill is None:
                raise RuntimeError("no active bill", bill_number)

            bill_path = biennium_path / bill_id.replace(" ", "/").lower()
            print(i, "/", len(bills_by_number), bill_path)

            short_description = ""
            if bill.ShortDescription is not None:
                short_description = bill.ShortDescription.text
            elif bill.LongDescription is not None:
                short_description = bill.LongDescription.text
            else:
                print("missing description")
                print(bill)
            bill_link = f"[{bill_id}]({str(bill_path.relative_to(biennium_path))}/) - {short_description}"
            if status.startswith("C "):
                bill_link = f"[{status} {bill_id}]({str(bill_path.relative_to(biennium_path))}/) - {short_description}"
                bills_by_status["passed"].append(bill_link)
            elif " " in status and not status.startswith("Gov") and not status.startswith("Del"):
                agency, short_committee = status.split(" ", maxsplit=1)
                acronym = None
                if short_committee in short_committee_status_to_acronym[agency]:
                    acronym = short_committee_status_to_acronym[agency][short_committee]
                # Do pass and do pass substitute
                elif short_committee.endswith("DPS"):
                    acronym = short_committee[:-3]
                elif short_committee.endswith("DP"):
                    acronym = short_committee[:-2]
                if not acronym:
                    if status not in bills_by_status:
                        bills_by_status[status] = []
                    bills_by_status[status].append(bill_link)
                else:
                    if acronym not in bills_by_status["committee"]:
                        bills_by_status["committee"][acronym] = []
                    bills_by_status["committee"][acronym].append(bill_link)
            else:
                if status not in bills_by_status:
                    bills_by_status[status] = []
                bills_by_status[status].append(bill_link)

            bill_readme = []

            bill_readme.append("# " + bill_id + " - " + short_description)
            sponsor = sponsors_by_id[sponsor]
            slug = sponsor.Email.text.split("@")[0].lower()
            bill_readme.append(f"**Primary Sponsor:** [{sponsor.Name.text}](/person/leg/{slug}.md)")
            bill_readme.append("")
            bill_link_by_number[bill_number] = f"[{bill_id}](/{str(bill_path)}/) - {short_description} | {bill.HistoryLine.text}"
            bill_readme.append("*Status: " + bill.HistoryLine.text + "* | " + f"[leg.wa.gov summary](https://app.leg.wa.gov/billsummary?BillNumber={bill_number}&Year=2021)")
            bill_readme.append("")
            bill_readme.append(bill.LongDescription.text)
            bill_readme.append("")
            bill_readme.append("## Revisions")
            # print(bill.CurrentStatus.IntroducedDate.text, bill.CurrentStatus.ActionDate.text)
            # print(bill.CurrentStatus.Status.text)
            if bill_number in amendments_by_bill_number:
                for amendment in amendments_by_bill_number[bill_number]:
                    # print(amendment.Name.text, amendment.SponsorName.text, amendment.Description.text, amendment.FloorAction.text)
                    # print(amendment)
                    # print()
                    url = amendment.PdfUrl.text
                    url = url.replace("Pdf", "Xml").replace("pdf", "xml")
                    # print(url)
                    # response = requests.get(url)
                    # if not response.ok:
                    #     print("missing xml version")
                    #     print(amendment)
                    # amendment_text = BeautifulSoup(response.content, 'xml')
                    # for section in amendment_text.find_all("AmendSection"):
                    #     # print(section.AmendItem.P.text)
                    #     new_sections = section.find_all("BillSection")
                    #     if not new_sections:
                    #         print(section)
                    #     print()
                    #print(amendment)
                    # print()
                    # print()
                # print(amendment)
            else:
                print("no amendments")
            if bill_number in docs_by_number:
                for doc in docs_by_number[bill_number]:
                    url = doc.PdfUrl.text
                    url = url.replace("Pdf", "Xml").replace("pdf", "xml")
                    commit_date = doc.PdfLastModifiedDate.text
                    print(doc.Name.text, commit_date, url)
                    revision = "1"
                    if "-" in doc.Name.text:
                        revision = doc.Name.text.split("-")[1]
                    revision_path = bill_path / revision
                    bill_readme.append("* [" + doc.ShortFriendlyName.text + "](" + str(revision_path.relative_to(bill_path)) + "/)")

                    text = requests.get(url).content
                    bill_text = BeautifulSoup(text, 'xml')
                    sections = {}
                    new_chapters = {}
                    sections_handled = 0
                    section_count = 0
                    revision_readme = ["# " + doc.LongFriendlyName.text]
                    revision_readme.append("")
                    revision_readme.append("[Source](" + doc.PdfUrl.text.replace(" ", "%20") + ")")
                    for section in bill_text.find_all("BillSection"):
                        section_number = section.BillSectionNumber
                        if not section_number:
                            continue
                        section_count += 1
                        section_number = section_number.Value.text
                        section_citation = f"2021 c XXX § {section_number}"
                        # print("Bill section", section_number, section.attrs)
                        if "action" not in section.attrs:
                            if section["type"] == "new":
                                lines = []
                                for paragraph in section.find_all("P"):
                                    lines.append(paragraph.text)
                                sections[section_number] = lines
                                sections_handled += 1
                                revision_readme.append("## Section " + section_number)
                                revision_readme.extend(format_lists(lines))
                                revision_readme.append("")
                            else:
                                pass
                                #print(section)
                        elif section["action"] == "repeal":
                            delete_section(revision_path, get_citation(section), section_citation)
                            sections_handled += 1
                        elif section["action"] == "amend":
                            # print("##", section.Caption.text)
                            section_lines = []

                            for paragraph in section.find_all("P"):
                                line = []
                                for child in paragraph.children:
                                    if isinstance(child, NavigableString):
                                        s = str(child)
                                        # Only non-whitespace strings. Don't always strip though
                                        # because we want the spaces on the edge of text.
                                        if s.strip():
                                            line.append(s)
                                    else:
                                        if child.name != "TextRun":
                                            if child.name == "SectionCite":
                                                line.append(child.text)
                                            elif child.name == "Hyphen" and child["type"] == "nobreak":
                                                line.append("‑")
                                            elif child.name not in ("Leader",):
                                                # print(paragraph, child)
                                                raise RuntimeError()
                                        if "amendingStyle" not in child.attrs:
                                            # print("no amend style", child.name, child)
                                            pass
                                        elif child["amendingStyle"] in AMEND_INCLUDE:
                                            stripped = child.text.strip()
                                            if not stripped:
                                                continue
                                            # Ignore changed bullets
                                            if stripped[0] == "(" and stripped[-1] == ")":
                                                line.append(child.text)
                                            elif stripped[0] == "(" and " " in stripped:
                                                paren_index = stripped.index(" ") + 1
                                                line.append(stripped[:paren_index] + "**" + stripped[paren_index:] + "**")
                                            else:
                                                line.append("**" + stripped + "**")
                                if line:
                                    section_lines.append("".join(line))
                            rcw_citation = get_citation(section)
                            amended_path = amend_section(revision_path, get_citation(section), section_citation, section_lines)

                            revision_readme.append("## Section " + section_number)
                            if amended_path is None:
                                revision_readme.append("> This section modifies existing unknown section.")
                            else:
                                revision_readme.append("> This section modifies existing section [" + ".".join(rcw_citation) + "](/" + str(section_path(rcw_citation)) + "). Here is the [modified chapter](" + str(amended_path.relative_to(revision_path)) + ") for context.")
                            revision_readme.append("")
                            revision_readme.extend(format_lists(section_lines))
                            revision_readme.append("")
                            sections_handled += 1
                        elif section["action"] == "addsect":
                            section_lines = []
                            for paragraph in section.find_all("P"):
                                section_lines.append(paragraph.text)
                            rcw_citation = get_citation(section)
                            if rcw_citation[0] is None:
                                print(section, section.attrs)
                                continue
                            amended_path = add_section(revision_path, get_citation(section), section_citation, section_lines)

                            revision_readme.append("## Section " + section_number)
                            if amended_path:
                                revision_readme.append("> This section adds a new section to an existing chapter [" +
                                                       ".".join(rcw_citation[:2]) +
                                                       "](/" +
                                                       str(section_path(rcw_citation)) +
                                                       "). Here is the [modified chapter](" +
                                                       str(amended_path.relative_to(revision_path)) +
                                                       ") for context.")
                            else:
                                revision_readme.append("> This section adds a new section to an unknown chapter " +
                                                       ".".join(rcw_citation[:2]))

                            revision_readme.append("")
                            revision_readme.extend(format_lists(section_lines))
                            revision_readme.append("")
                            sections_handled += 1
                        elif section["action"] == "addchap":
                            c = get_citation(section)
                            new_chapters[c] = set()
                            # print("add chapter to", )
                            if section.P is None:
                                print(section)
                                continue
                            text = section.P.text.split("of this act")[0]
                            for m in sections_pattern.finditer(text):
                                new_chapters[c].add(m[0])
                            for m in sections_through_pattern.finditer(text):
                                new_chapters[c].update((str(x) for x in range(int(m[1]), int(m[2]))))
                            # print(text)
                            # print(new_chapters[c])
                        elif section["action"] == "addmultisect":
                            # print("add chapter to", get_citation(section))
                            # print(section.P.text)
                            pass
                        elif section["action"] == "effdate":
                            # When sections of the bill go into effect. (PR merge date.)
                            # print("add chapter to", get_citation(section))
                            # print(section.P.text)
                            pass
                        elif section["action"] == "emerg":
                            # Emergency bill that would take immediate effect.
                            # print("add chapter to", get_citation(section))
                            # print(section.P.text)
                            pass
                        elif section["action"] == "repealuncod":
                            # Repeal a section of a session law that is uncodified.
                            pass
                        elif section["action"] == "amenduncod":
                            # Amend a section of a session law that is uncodified.
                            pass
                        elif section["action"] == "addsectuncod":
                            # Add a section of a session law that is uncodified.
                            pass
                        elif section["action"] == "remd":
                            # Reenact and amend a section. Looks like two bills from the same session
                            # changed the same location and the code revisor had to merge them.
                            pass
                        elif section["action"] == "expdate":
                            # Section expiration date.
                            pass
                        elif section["action"] == "recod":
                            # Recode sections.
                            pass
                        elif section["action"] == "decod":
                            # Section expiration date.
                            pass
                        else:
                            print(section, section.attrs)
                    print(f"{sections_handled}/{section_count}")
                    if new_chapters:
                        for c in new_chapters:
                            contents = []
                            chapter_name = ""
                            chapter_sections = sorted(new_chapters[c], key=int)
                            #print(chapter_sections)
                            for section in chapter_sections:
                                section_citation = f"2021 c XXX § {section}"
                                if section not in sections or not sections[section]:
                                    print("missing section", section)
                                    continue
                                contents.append((section_citation, section, sections.pop(section)))
                                if contents[-1][2][0].startswith("This chapter shall be known and cited as the "):
                                    chapter_name = contents[-1][2][0].split("the ", maxsplit=1)[1].strip(".")
                            if not chapter_name:
                                print("Missing chapter name")
                                continue
                            new_chapter(revision_path, c, chapter_name, contents)
                            print()
                            print()
                    if sections:
                        for section_number in sections:
                            # print(section_number, sections[section_number])
                            pass

                    revision_path.mkdir(parents=True, exist_ok=True)
                    rm = revision_path / "README.md"
                    rm.write_text("\n".join(revision_readme))
            
            rm = bill_path / "README.md"
            rm.write_text("\n".join(bill_readme))

            print()


        # print("------------------------")
        # print()

    unhandled_keys = set(bills_by_status.keys())

    def list_out(key):
        if key in bills_by_status:
            for b in bills_by_status[key]:
                biennium_readme.append("* " + b)
        biennium_readme.append("")
        unhandled_keys.discard(key)

    biennium_readme.append("## Senate")
    biennium_readme.append("### Second Reading")
    biennium_readme.append("Ready for second reading, debate and amendments.")
    list_out("S 2nd Reading")
    biennium_readme.append("### Third Reading")
    biennium_readme.append("Ready for third reading.")
    list_out("S 3rd Reading")
    biennium_readme.append("### Passed Third Reading")
    biennium_readme.append("Passed third reading. Ready for other house.")
    list_out("S Passed 3rd")

    for acronym, name in committees_by_agency["Senate"]:
        if acronym not in bills_by_status["committee"]:
            continue
        biennium_readme.append("### " + name)
        for b in bills_by_status["committee"][acronym]:
            biennium_readme.append("* " + b)
        biennium_readme.append("")

    biennium_readme.append("### Senate Rules")
    biennium_readme.append("Routes bills after committee.")
    biennium_readme.append("#### Senate X-File")
    biennium_readme.append("X-File where bills aren't going to be acted on.")
    list_out("S Rules X")
    biennium_readme.append("#### Senate Waiting Second Reading")
    biennium_readme.append("Bills waiting for second reading")
    list_out("S Rules 2")
    biennium_readme.append("#### Senate Waiting Third Reading")
    biennium_readme.append("Bills waiting for third reading")
    list_out("S Rules 3")
    list_out("S Rules 3C")

    biennium_readme.append("## House")
    biennium_readme.append("### Second Reading")
    biennium_readme.append("Ready for second reading, debate and amendments.")
    list_out("H 2nd Reading")
    biennium_readme.append("### Passed Third Reading")
    biennium_readme.append("Passed third reading. Ready for other house.")
    list_out("H Passed 3rd")

    for acronym, name in committees_by_agency["House"]:
        if acronym not in bills_by_status["committee"]:
            continue
        biennium_readme.append("### " + name)
        for b in bills_by_status["committee"][acronym]:
            biennium_readme.append("* " + b)
        biennium_readme.append("")

    unhandled_keys.discard("committee")

    biennium_readme.append("### House Rules")
    biennium_readme.append("Routes bills after committee.")
    biennium_readme.append("#### House X-File")
    biennium_readme.append("X-File where bills aren't going to be acted on.")
    list_out("H Rules X")
    biennium_readme.append("#### House Waiting Second Reading")
    biennium_readme.append("Bills waiting for second reading")
    list_out("H Rules R")
    biennium_readme.append("#### House Waiting Third Reading")
    biennium_readme.append("Bills waiting for third reading")
    list_out("H Rules C")
    list_out("H Rules 3C")

    biennium_readme.append("## Vetoed")
    list_out("Gov vetoed")

    biennium_readme.append("## Filed with Secretary of State")
    biennium_readme.append("Passed through legislature and governor. Waiting to be incorporated into session law.")
    list_out("H Filed Sec/St")

    list_out("S Filed Sec/St")

    biennium_readme.append("## Session Law")
    list_out("passed")


    biennium_readme.append("## Unknown Status")
    for k in sorted(unhandled_keys):
        biennium_readme.append("### " + k)
        list_out(k)

    rm = biennium_path / "README.md"
    rm.write_text("\n".join(biennium_readme))

    for sponsor_id in bills_by_sponsor:
        sponsor = sponsors_by_id[sponsor_id]
        email = sponsor.Email.text
        slug = email.split("@")[0].lower()
        person_page = pathlib.Path(f"person/leg/{slug}.md")

        if not person_page.exists():
            print("missing", person_page)
            continue

        lines = person_page.read_text().split("\n")
        if "## Bills" in lines:
            lines = lines[:lines.index("## Bills")]
        lines.append("## Bills")
        for bill_number in bills_by_sponsor[sponsor_id]:
            lines.append("* " + bill_link_by_number[bill_number])
        lines.append("")
        person_page.write_text("\n".join(lines))

    print()    
    break

rm = bills_path / "README.md"
rm.write_text("\n".join(all_bills_readme))
