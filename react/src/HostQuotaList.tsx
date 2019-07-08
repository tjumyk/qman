import React from "react";
import {BasicError, HostQuota} from "./models";
import {HostQuotaView} from "./HostQuotaView";
import {ErrorMessage} from "./ErrorMessage";


interface HostQuotasState {
    error?: BasicError;
    loading: boolean;
    data: { [host: string]: HostQuota };
}

export class HostQuotaList extends React.Component<{}, HostQuotasState> {
    constructor(props: any) {
        super(props);
        this.state = {
            error: undefined,
            loading: false,
            data: {}
        }
    }

    componentDidMount(): void {
        this.setState({loading: true});
        fetch("api/quotas")
            .then(res => {
                res.json().then(json => {
                    if (res.ok) {
                        let result = json as { [host: string]: HostQuota };
                        this.setState({data: result})
                    } else {
                        let error = json as BasicError;
                        this.setState({error: error})
                    }
                }).catch(() => {
                    this.setState({error: {msg: 'Unexpected Error'}})
                })
            })
            .catch(() => {
                this.setState({error: {msg: 'Connection Error'}})
            })
            .finally(() => {
                this.setState({loading: false})
            })
    }

    render() {
        if (this.state.error) {
            return (
                <div className="container">
                    <ErrorMessage error={this.state.error}/>
                </div>
            )
        }
        if (this.state.loading) {
            return (
                <section className="section">
                    <div className="container has-text-centered">
                        <p className="title">
                            <span className="icon is-large">
                                <i className="fas fa-spinner fa-pulse"/>
                            </span>
                        </p>
                        <p className="subtitle">Loading...</p>
                    </div>
                </section>
            )
        }
        const itemViews = [];
        for (let key of Object.keys(this.state.data)) {
            let value = this.state.data[key];
            itemViews.push(<HostQuotaView host={key} data={value}/>)
        }
        return itemViews;
    }
}
