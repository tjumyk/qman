export interface BasicError{
    msg: string;
    detail?: string;
}

export interface DiskUsage {
    free: number;
    used: number;
    total: number;
    percent: number;
}

export interface QuotaInfo {
    block_grace: number;
    inode_grace: number;
    flags: number;
}

export interface Quota {
    block_hard_limit: number;
    block_soft_limit: number;
    block_current: number;
    inode_hard_limit: number;
    inode_soft_limit: number;
    inode_current: number;
    block_time_limit: number;
    inode_time_limit: number;
}

export interface UserQuota extends Quota{
    name: string;
    uid: number;
}

export interface GroupQuota extends Quota{
    name: string;
    gid: number;
}

export interface DeviceQuota{
    fstype: string;
    mount_points: string[];
    name: string;
    opts: string[];
    usage: DiskUsage;

    user_quota_format?: string;
    user_quota_info?: QuotaInfo;
    user_quotas?: UserQuota[];

    group_quota_format?: string;
    group_quota_info?: QuotaInfo;
    group_quotas?: GroupQuota[];
}

export interface HostQuota {
    results?: DeviceQuota[]
    error?: BasicError;
}
