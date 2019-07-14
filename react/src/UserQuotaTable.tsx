import React from "react";
import {BasicError, UserQuota} from "./models";
import {BlockSize} from "./BlockSize";
import {GraceTimestamp} from "./GraceTimestamp";
import {INodeSize} from "./INodeSize";

import "./QuotaTable.scss";
import {BlockLimitEditor} from "./BlockLimitEditor";

interface UserQuotaTableRowProps {
    host: string;
    device: string;
    quota: UserQuota;
}

interface UserQuotaTableRowState {
    editing: boolean;
    saving: boolean;
    quota: UserQuota;
    new_block_soft_limit: number;
    new_block_hard_limit: number;
    new_inode_soft_limit: number;
    new_inode_hard_limit: number;
}

class UserQuotaTableRow extends React.Component<UserQuotaTableRowProps, UserQuotaTableRowState> {
    constructor(props: UserQuotaTableRowProps) {
        super(props);
        this.state = {
            editing: false,
            saving: false,
            quota: props.quota,
            new_block_soft_limit: props.quota.block_soft_limit,
            new_block_hard_limit: props.quota.block_hard_limit,
            new_inode_soft_limit: props.quota.inode_soft_limit,
            new_inode_hard_limit: props.quota.inode_hard_limit
        };
    }

    startEdit() {
        this.setState({
            editing: true,
            new_block_soft_limit: this.state.quota.block_soft_limit,
            new_block_hard_limit: this.state.quota.block_hard_limit,
            new_inode_soft_limit: this.state.quota.inode_soft_limit,
            new_inode_hard_limit: this.state.quota.inode_hard_limit
        });
    }

    saveEdit() {
        this.setState({saving: true});
        fetch(`api/quotas/${this.props.host}/users/${this.state.quota.uid}?device=${encodeURIComponent(this.props.device)}`, {
            body: JSON.stringify({
                block_hard_limit: this.state.new_block_hard_limit,
                block_soft_limit: this.state.new_block_soft_limit,
                inode_hard_limit: this.state.new_inode_hard_limit,
                inode_soft_limit: this.state.new_inode_soft_limit,
            }),
            cache: "no-cache",
            headers: {
                'content-type': 'application/json'
            },
            method: 'PUT'
        }).then(resp => {
            resp.json().then(json => {
                if (resp.ok) {
                    let quota = json as UserQuota;
                    this.setState({quota})
                } else {
                    let error = json as BasicError;
                    console.error(error);
                    alert(JSON.stringify(error))
                }
            }).catch(() => {
                let error = "Unexpected Error";
                console.error(error);
                alert(error)
            });
        }).catch(() => {
            let error = "Connection Error";
            console.error(error);
            alert(error)
        }).finally(() => {
            this.setState({editing: false, saving: false});
        })
    }

    cancelEdit() {
        this.setState({editing: false});
    }

    getQuotaClass(quota: UserQuota): string {
        let quotaClass = '';
        if ((quota.block_soft_limit > 0 && quota.block_current >= quota.block_soft_limit * 1024) ||
            (quota.inode_soft_limit > 0 && quota.inode_current >= quota.inode_soft_limit))
            quotaClass = 'is-warning';
        if ((quota.block_hard_limit > 0 && quota.block_current >= quota.block_hard_limit * 1024) ||
            (quota.inode_hard_limit > 0 && quota.inode_current >= quota.inode_hard_limit))
            quotaClass = 'is-danger';
        return quotaClass
    }

    render() {
        return (
            <tr className={this.getQuotaClass(this.state.quota)}>
                <td>{this.state.quota.uid}</td>
                <td>{this.state.quota.name}</td>
                <td><BlockSize size={this.state.quota.block_current}/></td>
                <td>
                    {this.state.editing ?
                        <BlockLimitEditor initValue={this.state.quota.block_soft_limit} onChange={(val) => {
                            this.setState({new_block_soft_limit: val})
                        }}/>
                        : <BlockSize size={this.state.quota.block_soft_limit * 1024}/>}
                </td>
                <td>
                    {this.state.editing ?
                        <BlockLimitEditor initValue={this.state.quota.block_hard_limit} onChange={(val) => {
                            this.setState({new_block_hard_limit: val})
                        }}/>
                        : <BlockSize size={this.state.quota.block_hard_limit * 1024}/>}
                </td>
                <td><GraceTimestamp time={this.state.quota.block_time_limit}/></td>
                <td><INodeSize size={this.state.quota.inode_current}/></td>
                <td>
                    {this.state.editing ?
                        <input className="input" type="number" min="0" value={this.state.new_inode_soft_limit}
                               onChange={(e) => this.setState({new_inode_soft_limit: parseInt(e.target.value) || 0})}/>
                        : <INodeSize size={this.state.quota.inode_soft_limit}/>}
                </td>
                <td>
                    {this.state.editing ?
                        <input className="input" type="number" min="0" value={this.state.new_inode_hard_limit}
                               onChange={(e) => this.setState({new_inode_hard_limit: parseInt(e.target.value) || 0})}/>
                        : <INodeSize size={this.state.quota.inode_hard_limit}/>}
                </td>
                <td><GraceTimestamp time={this.state.quota.inode_time_limit}/></td>
                <td>
                    <div className="buttons are-small">
                        {
                            this.state.editing ?
                                <>
                                    <button className={"button is-primary" + (this.state.saving ? " is-loading" : "")}
                                            onClick={() => this.saveEdit()} disabled={this.state.saving}>
                                        <span className="icon is-small">
                                            <i className="fas fa-check"/>
                                        </span>
                                        <span>Save</span>
                                    </button>
                                    <button className="button is-danger" onClick={() => this.cancelEdit()}
                                            disabled={this.state.saving}>
                                        <span className="icon is-small">
                                            <i className="fas fa-times"/>
                                        </span>
                                        <span>Cancel</span>
                                    </button>
                                </>
                                :
                                <button className="button" onClick={() => this.startEdit()}>
                                    <span className="icon is-small">
                                        <i className="fas fa-cog"/>
                                    </span>
                                    <span>Edit</span>
                                </button>
                        }
                    </div>
                </td>
            </tr>
        )
    }
}

interface UserQuotaTableProps {
    host: string;
    device: string;
    quotas: UserQuota[]
}

export const UserQuotaTable: React.FC<UserQuotaTableProps> = props => {
    return (
        <table className="table quota is-hoverable is-striped">
            <thead>
            <tr>
                <th>uid</th>
                <th>name</th>
                <th>block used</th>
                <th>block soft limit</th>
                <th>block hard limit</th>
                <th>block grace time</th>
                <th>inode used</th>
                <th>inode soft limit</th>
                <th>inode hard limit</th>
                <th>inode grace time</th>
                <th>Operations</th>
            </tr>
            </thead>
            <tbody>
            {props.quotas.map(quota => <UserQuotaTableRow host={props.host} device={props.device} quota={quota}/>)}
            </tbody>
        </table>
    )
};
