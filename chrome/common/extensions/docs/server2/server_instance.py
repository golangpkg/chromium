# Copyright (c) 2012 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from api_categorizer import APICategorizer
from api_data_source import APIDataSource
from api_list_data_source import APIListDataSource
from api_models import APIModels
from availability_finder import AvailabilityFinder
from compiled_file_system import CompiledFileSystem
from content_providers import ContentProviders
from document_renderer import DocumentRenderer
from empty_dir_file_system import EmptyDirFileSystem
from environment import IsDevServer
from features_bundle import FeaturesBundle
from gcs_file_system_provider import CloudStorageFileSystemProvider
from github_file_system_provider import GithubFileSystemProvider
from host_file_system_iterator import HostFileSystemIterator
from host_file_system_provider import HostFileSystemProvider
from object_store_creator import ObjectStoreCreator
from reference_resolver import ReferenceResolver
from samples_data_source import SamplesDataSource
from table_of_contents_renderer import TableOfContentsRenderer
from template_renderer import TemplateRenderer
from test_branch_utility import TestBranchUtility
from test_object_store import TestObjectStore


class ServerInstance(object):

  def __init__(self,
               object_store_creator,
               compiled_fs_factory,
               branch_utility,
               host_file_system_provider,
               github_file_system_provider,
               gcs_file_system_provider,
               base_path='/'):
    '''
    |object_store_creator|
        The ObjectStoreCreator used to create almost all caches.
    |compiled_fs_factory|
        Factory used to create CompiledFileSystems, a higher-level cache type
        than ObjectStores. This can usually be derived from just
        |object_store_creator| but under special circumstances a different
        implementation needs to be passed in.
    |branch_utility|
        Has knowledge of Chrome branches, channels, and versions.
    |host_file_system_provider|
        Creates FileSystem instances which host the server at alternative
        revisions.
    |github_file_system_provider|
        Creates FileSystem instances backed by GitHub.
    |base_path|
        The path which all HTML is generated relative to. Usually this is /
        but some servlets need to override this.
    '''
    self.object_store_creator = object_store_creator

    self.compiled_fs_factory = compiled_fs_factory

    self.host_file_system_provider = host_file_system_provider
    host_fs_at_trunk = host_file_system_provider.GetTrunk()

    self.github_file_system_provider = github_file_system_provider
    self.gcs_file_system_provider = gcs_file_system_provider

    assert base_path.startswith('/') and base_path.endswith('/')
    self.base_path = base_path

    self.host_file_system_iterator = HostFileSystemIterator(
        host_file_system_provider,
        branch_utility)

    self.features_bundle = FeaturesBundle(
        host_fs_at_trunk,
        self.compiled_fs_factory,
        self.object_store_creator)

    self.api_models = APIModels(
        self.features_bundle,
        self.compiled_fs_factory,
        host_fs_at_trunk)

    self.availability_finder = AvailabilityFinder(
        branch_utility,
        compiled_fs_factory,
        self.host_file_system_iterator,
        host_fs_at_trunk,
        object_store_creator)

    self.api_categorizer = APICategorizer(
        host_fs_at_trunk,
        compiled_fs_factory)

    self.api_data_source_factory = APIDataSource.Factory(
        self.compiled_fs_factory,
        host_fs_at_trunk,
        self.availability_finder,
        self.api_models,
        self.object_store_creator)

    self.api_list_data_source_factory = APIListDataSource.Factory(
        self.compiled_fs_factory,
        host_fs_at_trunk,
        self.features_bundle,
        self.object_store_creator,
        self.api_models,
        self.availability_finder,
        self.api_categorizer)

    self.ref_resolver_factory = ReferenceResolver.Factory(
        self.api_data_source_factory,
        self.api_models,
        object_store_creator)

    self.api_data_source_factory.SetReferenceResolverFactory(
        self.ref_resolver_factory)

    # Note: samples are super slow in the dev server because it doesn't support
    # async fetch, so disable them.
    if IsDevServer():
      extension_samples_fs = EmptyDirFileSystem()
      app_samples_fs = EmptyDirFileSystem()
    else:
      extension_samples_fs = host_fs_at_trunk
      # TODO(kalman): Re-enable the apps samples, see http://crbug.com/344097.
      app_samples_fs = EmptyDirFileSystem()
      #app_samples_fs = github_file_system_provider.Create(
      #    'GoogleChrome', 'chrome-app-samples')
    self.samples_data_source_factory = SamplesDataSource.Factory(
        extension_samples_fs,
        app_samples_fs,
        CompiledFileSystem.Factory(object_store_creator),
        self.ref_resolver_factory,
        base_path)

    self.api_data_source_factory.SetSamplesDataSourceFactory(
        self.samples_data_source_factory)

    self.content_providers = ContentProviders(
        object_store_creator,
        self.compiled_fs_factory,
        host_fs_at_trunk,
        self.github_file_system_provider,
        self.gcs_file_system_provider)

    # TODO(kalman): Move all the remaining DataSources into DataSourceRegistry,
    # then factor out the DataSource creation into a factory method, so that
    # the entire ServerInstance doesn't need to be passed in here.
    self.template_renderer = TemplateRenderer(self)

    # TODO(kalman): It may be better for |document_renderer| to construct a
    # TemplateDataSource itself rather than depending on template_renderer, but
    # for that the above todo should be addressed.
    self.document_renderer = DocumentRenderer(
        TableOfContentsRenderer(host_fs_at_trunk,
                                compiled_fs_factory,
                                self.template_renderer),
        self.ref_resolver_factory.Create())

  @staticmethod
  def ForTest(file_system=None, file_system_provider=None, base_path='/'):
    object_store_creator = ObjectStoreCreator.ForTest()
    if file_system is None and file_system_provider is None:
      raise ValueError('Either |file_system| or |file_system_provider| '
                       'must be specified')
    if file_system and file_system_provider:
      raise ValueError('Only one of |file_system| and |file_system_provider| '
                       'can be specified')
    if file_system_provider is None:
      file_system_provider = HostFileSystemProvider.ForTest(
          file_system,
          object_store_creator)
    return ServerInstance(object_store_creator,
                          CompiledFileSystem.Factory(object_store_creator),
                          TestBranchUtility.CreateWithCannedData(),
                          file_system_provider,
                          GithubFileSystemProvider.ForEmpty(),
                          CloudStorageFileSystemProvider(object_store_creator),
                          base_path=base_path)

  @staticmethod
  def ForLocal():
    object_store_creator = ObjectStoreCreator(start_empty=False,
                                              store_type=TestObjectStore)
    host_file_system_provider = HostFileSystemProvider.ForLocal(
        object_store_creator)
    return ServerInstance(
        object_store_creator,
        CompiledFileSystem.Factory(object_store_creator),
        TestBranchUtility.CreateWithCannedData(),
        host_file_system_provider,
        GithubFileSystemProvider.ForEmpty(),
        CloudStorageFileSystemProvider(object_store_creator))
