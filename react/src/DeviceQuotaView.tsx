import {DeviceQuota} from "./models";
import React from "react";
import {BlockSize} from "./BlockSize";
import {UserQuotaTable} from "./UserQuotaTable";

import './DeviceQuotaView.scss';

interface DeviceQuotaViewProps {
    host: string;
    data: DeviceQuota;
}

export const DeviceQuotaView: React.FC<DeviceQuotaViewProps> = (props) => {
    let user_quota_table;
    if (props.data.user_quotas) {
        user_quota_table = (
            <UserQuotaTable host={props.host} device={props.data.name} quotas={props.data.user_quotas}/>
        )
    }

    return (
        <div className="card device-quota">
            <div className="card-content">
                <div className="content">
                    <div className="level">
                        <div className="level-item has-text-centered">
                            <div>
                                <p className="heading">Device</p>
                                <p className="title">{props.data.name}</p>
                            </div>
                        </div>
                        <div className="level-item has-text-centered">
                            <div>
                                <p className="heading">Filesystem Type</p>
                                <p className="title">{props.data.fstype}</p>
                            </div>
                        </div>
                        <div className="level-item has-text-centered">
                            <div>
                                <p className="heading">Mount Points</p>
                                <p className="title">{props.data.mount_points.join(', ')}</p>
                            </div>
                        </div>
                        <div className="level-item has-text-centered">
                            <div>
                                <p className="heading">Mount Options</p>
                                <p className="subtitle">{props.data.opts.join(', ')}</p>
                            </div>
                        </div>
                    </div>
                    <div className="level has-text-centered">
                        <div className="progress-item">
                            <progress className="progress" value={props.data.usage.percent}
                                      max="100">{props.data.usage.percent}%
                            </progress>
                            <p><BlockSize size={props.data.usage.used}/> / <BlockSize size={props.data.usage.total}/>
                            </p>
                        </div>
                    </div>
                    {user_quota_table}
                </div>
            </div>
        </div>
    )
};
