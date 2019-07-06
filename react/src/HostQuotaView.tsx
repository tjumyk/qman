import React from "react";
import {HostQuota} from "./models";
import {ErrorMessage} from "./ErrorMessage";

import {DeviceQuotaView} from "./DeviceQuotaView";


interface HostQuotaViewProps {
    host: string;
    data: HostQuota;
}

export const HostQuotaView: React.FC<HostQuotaViewProps> = (props) => {
    let content;
    if (props.data.error) {
        content = <ErrorMessage error={props.data.error}/>
    } else if (props.data.results) {
        content = props.data.results.map(data => <DeviceQuotaView host={props.host} data={data}/>)
    }
    return (
        <section className="section">
            <div className="container">
                <h1 className="title is-4">
                    <span className="icon" style={{marginRight: '.5em'}}>
                        <i className="fas fa-desktop"/>
                    </span>
                    {props.host}
                </h1>
                {content}
            </div>
        </section>
    )
};
