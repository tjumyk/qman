import React from "react";

interface BlockLimitEditorProps {
    initValue: number;
    onChange: (value: number) => void
}

interface BlockLimitEditorState {
    value: number;
    unitIndex: number;
}

const units = [
    'KB', 'MB', 'GB', 'TB'
];

export class BlockLimitEditor extends React.Component<BlockLimitEditorProps, BlockLimitEditorState> {
    constructor(props: BlockLimitEditorProps) {
        super(props);

        // find the best exact unit
        let value = props.initValue;
        let unitIndex = 0;  // assume input is in the lowest unit
        while(value > 0 && value % 1024 === 0 && unitIndex < units.length - 1){
            value /= 1024;
            ++unitIndex;
        }

        this.state = {
            value,
            unitIndex
        }
    }

    onChange(value: number, unitIndex: number){
        if(this.props.onChange){
            // output with lowest unit
            while(unitIndex > 0){
                value *= 1024;
                --unitIndex;
            }
            value = Math.round(value);
            this.props.onChange(value)
        }
    }

    onValueChange(rawValue: string){
        if(rawValue){
            let value = parseFloat(rawValue);
            this.setState({value});
            this.onChange(value, this.state.unitIndex);
        }
    }

    onUnitChange(rawNewUnitIndex: string){
        if(!rawNewUnitIndex)
            return;
        let newUnitIndex = parseInt(rawNewUnitIndex);

        let value = this.state.value;
        let unitIndex = this.state.unitIndex;

        if(unitIndex < newUnitIndex){
            while(unitIndex < newUnitIndex){
                value = value / 1024;
                ++unitIndex;
            }
            value = Math.round(value * 100) / 100;
        }
        else if(unitIndex > newUnitIndex){
            while(unitIndex > newUnitIndex){
                value = value * 1024;
                --unitIndex;
            }
        }

        this.setState({
            value,
            unitIndex
        });

        this.onChange(value, unitIndex);
    }

    render() {
        return (
            <div className="field has-addons">
                <div className="control">
                    <input className="input" type="number" min="0" value={this.state.value} onChange={(e)=>this.onValueChange(e.target.value)}/>
                </div>
                <div className="control">
                    <span className="select">
                        <select value={this.state.unitIndex} onChange={(e)=>this.onUnitChange(e.target.value)}>
                            {units.map((unit, idx)=><option value={idx}>{unit}</option>)}
                        </select>
                    </span>
                </div>
            </div>
        )
    }
}