import React from "react";

interface INodeSizeProps {
    size: number;
}

export const INodeSize:React.FC<INodeSizeProps> = props => {
    let num = props.size;
    if(num > 10000){
        num = Math.round(num/1000);
        return <>{num}k</>
    }
    return <>{num}</>
};
