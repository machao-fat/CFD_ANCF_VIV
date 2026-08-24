"""Stage94 isolated campaign adapter for the persistent MATLAB worker seam."""

from .adapter import PersistentMatlabCampaignAdapter, CampaignAdapterError, patch_campaign_factory

__all__ = ["PersistentMatlabCampaignAdapter", "CampaignAdapterError", "patch_campaign_factory"]
