"""Plugin for execution with serverSHARK."""

import sys
import logging
import timeit
import re

from mongoengine import connect, DoesNotExist
from pycoshark.mongomodels import VCSSystem, Commit, IssueSystem, Issue, Project
from pycoshark.utils import create_mongodb_uri_string


class LinkSHARK:
    """Determines linked issues for commits
    """

    def __init__(self):
        """
        Default constructor.
        """
        self._log = logging.getLogger("main")
        # precompile regex
        self._direct_link_jira = re.compile('(?P<ID>[A-Z][A-Z0-9_]+-[0-9]+)', re.M)
        self._direct_link_bz = re.compile('(bug|issue|bugzilla)[s]{0,1}[#\s]*(?P<ID>[0-9]+)', re.I | re.M)
        self._direct_link_gh = re.compile('(bug|issue|close|fixes)[s]{0,1}[#\s]*(?P<ID>[0-9]+)', re.I | re.M)
        pass

    def start(self, cfg):
        """
        Executes the linkSHARK.
        :param cfg: configuration object that is used
        """
        self._log.setLevel(cfg.get_debug_level())
        start_time = timeit.default_timer()

        uri = create_mongodb_uri_string(cfg.user, cfg.password, cfg.host, cfg.port, cfg.authentication_db,
                                        cfg.ssl_enabled)
        connect(cfg.db_database, host=uri)

        # Get the id of the project for which the code entities shall be merged
        try:
            project_id = Project.objects(name=cfg.project_name).get().id
        except DoesNotExist:
            self._log.error('Project %s not found!' % cfg.project_name)
            sys.exit(1)

        vcs_system = VCSSystem.objects(project_id=project_id).get()

        self._itss = []
        for its in IssueSystem.objects.filter(project_id=project_id):
            self._itss.append(its)

        self._log.info("Starting issue linking")

        for commit in Commit.objects.filter(vcs_system_id=vcs_system.id):
            issue_links = self._get_issue_links(commit)
            if len(issue_links) > 0:
                commit.linked_issue_ids = issue_links
                commit.save()

        elapsed = timeit.default_timer() - start_time
        self.logger.info("Execution time: %0.5f s" % elapsed)

    def _get_issue_links(self, commit):
        issue_links = []
        for its in self._itss:
            if 'jira' in its.url:
                issues = self._jira_issues(its, commit.message)
            elif 'bugzilla' in its.url:
                issues = self._bz_issues(its, commit.message)
            elif 'github' in its.url:
                issues = self._gh_issues(its, commit.message)

            # linked issues are collected regardless of issue type
            for r in issues:
                if r.id in issue_links:
                    continue
                issue_links.append(r.id)
        return issue_links

    def _gh_label(self, issue_system, message):
        ret = []
        for m in self._direct_link_gh.finditer(message):
            try:
                i = Issue.objects.get(issue_system_id=issue_system.id, external_id=m.group('ID').upper())
                ret.append(i)

            except Issue.DoesNotExist:
                self._error('issue: {} does not exist'.format(m.group('ID')))
                pass
        return ret

    def _bz_label(self, issue_system, message):
        ret = []
        for m in self._direct_link_bz.finditer(message):
            try:
                i = Issue.objects.get(issue_system_id=issue_system.id, external_id=m.group('ID').upper())
                ret.append(i)

            except Issue.DoesNotExist:
                # self._log.error('issue: {} does not exist'.format(m.group(1)))
                self._error('issue: {} does not exist'.format(m.group('ID')))
                pass
        return ret

    def _jira_label(self, issue_system, message):
        ret = []
        for m in self._direct_link_jira.finditer(message):
            try:
                i = Issue.objects.get(issue_system_id=issue_system.id, external_id=m.group('ID').upper())
                ret.append(i)

            except Issue.DoesNotExist:
                # self._log.error('issue: {} does not exist'.format(m.group(0)))
                self._error('issue: {} does not exist'.format(m.group('ID')))
                pass
        return ret

    def _error(self, message):
        # we log to warn because error gets to stdout in servershark
        self._log.warn(message)