"""Release boundaries: no mixed builds, partial uploads or overwritten releases."""
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'packaging'))
import release_tools as meta
import publish_release as release
import disk_image

SHA = 'a' * 40


class DiskImageTests(unittest.TestCase):
    def test_busy_retry_is_bounded_and_can_recover(self):
        busy = subprocess.CompletedProcess(['hdiutil'], 1, 'hdiutil: create failed - Resource busy\n')
        done = subprocess.CompletedProcess(['hdiutil'], 0, 'created\n')
        with patch('disk_image.subprocess.run', side_effect=[busy, done]) as run, patch('disk_image.time.sleep') as pause:
            disk_image.create_image(['hdiutil'])
            self.assertEqual(run.call_count, 2);pause.assert_called_once_with(5)
        with patch('disk_image.subprocess.run', return_value=busy) as run, patch('disk_image.time.sleep'):
            with self.assertRaises(subprocess.CalledProcessError):disk_image.create_image(['hdiutil'])
            self.assertEqual(run.call_count, 3)

    def test_other_errors_are_not_retried(self):
        error = subprocess.CompletedProcess(['hdiutil'], 1, 'No space left on device\n')
        with patch('disk_image.subprocess.run', return_value=error) as run, patch('disk_image.time.sleep') as pause:
            with self.assertRaises(subprocess.CalledProcessError):disk_image.create_image(['hdiutil'])
            self.assertEqual(run.call_count, 1);pause.assert_not_called()


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.version = meta.version_info()['version']
        for target in meta.PLATFORMS:
            path = self.root / meta.installer_name(self.version, target)
            path.write_bytes(('installer ' + target).encode())
            report = {'platform':target,'version':self.version,'commit':SHA,
                      'filename':path.name,'size':path.stat().st_size,'sha256':meta.digest(path),
                      'native':{'native':{'welcome':True,'bridge':True,'art':{'count':25,'failed':[],'ready':True}},
                                'self_check':{'version':self.version,'words':21244,'audio':24},'worker':'error recorded','speech':{'backend':'kokoro','files':['turn_00.wav']}},
                      'assistant':{'ready':True,'phase':'done','model':['qwen3:1.7b']}}
            (self.root / ('build-report-' + target + '.json')).write_text(json.dumps(report))

    def change_report(self, change):
        path = self.root / 'build-report-Windows-x64.json'
        data = json.loads(path.read_text()); change(data); path.write_text(json.dumps(data))

    def test_complete_build_and_tampered_installer(self):
        self.assertEqual(len(meta.validate_artifacts(self.root,self.version,SHA)),3)
        (self.root / meta.installer_name(self.version,'Windows-x64')).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'checksum'):
            meta.validate_artifacts(self.root,self.version,SHA)

    def test_missing_platform_is_not_publishable(self):
        (self.root / 'build-report-macOS-arm64.json').unlink()
        with self.assertRaisesRegex(ValueError,'Missing'):
            meta.validate_artifacts(self.root,self.version,SHA)

    def test_other_commit_or_version_cannot_be_mixed_in(self):
        for field, value in [('commit','b'*40),('version','1.0.0')]:
            with self.subTest(field=field):
                self.change_report(lambda r:r.update({field:value}))
                with self.assertRaisesRegex(ValueError,'mismatch'):
                    meta.validate_artifacts(self.root,self.version,SHA)
                self.change_report(lambda r:r.update(commit=SHA,version=self.version))

    def test_incomplete_ai_test_is_not_publishable(self):
        self.change_report(lambda r:r['assistant'].update(phase='error',model=[]))
        with self.assertRaisesRegex(ValueError,'model not verified'):
            meta.validate_artifacts(self.root,self.version,SHA)

    def test_duplicate_installer_is_rejected(self):
        extra = self.root / 'other'; extra.mkdir()
        filename = meta.installer_name(self.version,'Windows-x64')
        (extra / filename).write_bytes((self.root / filename).read_bytes())
        with self.assertRaisesRegex(ValueError,'duplicate installer'):
            meta.validate_artifacts(self.root,self.version,SHA)

    def test_bundle_contains_matching_source_and_checksums(self):
        def archive(command, **kwargs):
            self.assertEqual(command[-1], SHA)
            Path(command[command.index('-o')+1]).write_bytes(b'source archive')
        out = self.root / 'release'
        with patch('publish_release.subprocess.run',side_effect=archive):
            info, files, body = release.assemble(self.root,out,SHA,'FeeChain/maidcafe','https://example.org/run')
        self.assertEqual(len(files),8)
        sums = next(p for p in files if p.name.endswith('SHA256SUMS.txt'))
        for line in sums.read_text().splitlines():
            digest, name = line.split('  ')
            self.assertEqual(digest,meta.digest(out/name))
        self.assertIn(SHA,body)
        self.assertIn(info['tag'],body)


class ReleaseTests(unittest.TestCase):
    def test_current_version_and_notes_are_ready(self):
        info = meta.version_info()
        notes = (ROOT/'packaging/notes'/(info['version']+'.md')).read_text(encoding='utf-8')
        self.assertTrue(notes.startswith('# '+info['version']+'\n'))
        self.assertIn(info['version'],meta.render_install_guide())
        self.assertNotIn('{VERSION}',meta.render_install_guide())

    def test_version_order_and_validation(self):
        self.assertLess(meta.version_key('0.4.0-rc.1'),meta.version_key('0.4.0'))
        self.assertLess(meta.version_key('0.4.0-preview'),meta.version_key('0.4.0-preview.2'))
        for bad in ('../x','1.0','v1.0.0','01.0.0','1.0.0;touch x'):
            with self.assertRaises(ValueError): meta.version_info(bad)

    def test_existing_public_release_is_immutable_even_after_more_commits(self):
        existing={'tag_name':'v0.3.0-preview','draft':False,'target_commitish':'b'*40,'html_url':'published'}
        self.assertEqual(release.release_decision([existing],'0.3.0-preview',SHA)[0],'skip')
        with patch('publish_release.gh',return_value=json.dumps([[existing]])) as gh, patch('publish_release.api') as api:
            self.assertIn('no files changed',release.publish('FeeChain/maidcafe',meta.version_info('0.3.0-preview'),SHA,[],'body'))
        self.assertEqual(gh.call_count,1); api.assert_not_called()

    def test_draft_resume_requires_same_source_and_ownership(self):
        draft={'tag_name':'v0.3.1-preview','draft':True,'target_commitish':SHA,
               'body':'<!-- maidcafe-source:'+SHA+' -->'}
        self.assertEqual(release.release_decision([draft],'0.3.1-preview',SHA)[0],'resume')
        with self.assertRaisesRegex(ValueError,'unrelated draft'):
            release.release_decision([draft],'0.3.1-preview','b'*40)

    def test_accidental_version_regression_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'higher version'):
            release.release_decision([{'tag_name':'v0.4.0','draft':False}],'0.3.2-preview',SHA)

    def test_upload_validation_requires_every_matching_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'installer.exe'; p.write_bytes(b'installer')
            good={'name':p.name,'size':p.stat().st_size,'digest':'sha256:'+meta.digest(p)}
            release.verify_uploads([good],[p])
            for assets in ([],[dict(good,size=1)],[dict(good,digest='bad')],[good,good]):
                with self.assertRaises(ValueError): release.verify_uploads(assets,[p])

    def test_bad_upload_never_publishes_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'installer.exe';p.write_bytes(b'installer')
            replies=[[],{'id':1,'assets':[]},{'id':1,'assets':[]}]
            with patch('publish_release.gh',return_value='[[]]'),patch('publish_release.api',side_effect=replies) as api:
                with self.assertRaisesRegex(ValueError,'incomplete'):
                    release.publish('FeeChain/maidcafe',meta.version_info('0.3.1-preview'),SHA,[p],'body')
            self.assertFalse(any(len(c.args)>1 and c.args[1]=='PATCH' for c in api.call_args_list))
            self.assertTrue(api.call_args_list[1].args[2]['draft'])

    def test_pull_request_cannot_publish(self):
        with patch.dict(os.environ,{'GITHUB_REF':'refs/pull/1/merge','GITHUB_EVENT_NAME':'pull_request'}), \
                patch.object(sys,'argv',['publish_release.py','--publish']),patch('publish_release.publish') as publish:
            with self.assertRaisesRegex(ValueError,'main workflow'):
                release.main()
        publish.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
