import React from "react";
import moment, {Moment} from "moment";

interface GraceTimestampProps {
    time: number
}

interface GraceTimestampState {
    now: Moment;
}

export class GraceTimestamp extends React.Component<GraceTimestampProps, GraceTimestampState> {
    timerID: any = 0;

    constructor(props: GraceTimestampProps) {
        super(props);
        this.state = {
            now: moment()
        };
    }

    componentDidMount(): void {
        this.timerID = setInterval(
            () => this.tick(),
            1000 * 30
        )
    }

    componentWillUnmount(): void {
        clearInterval(this.timerID)
    }

    tick() {
        this.setState({
            now: moment()
        })
    }

    render() {
        if(this.props.time)
            return <>{moment.unix(this.props.time).from(this.state.now)}</>;
        return <>0</>
    }
}
