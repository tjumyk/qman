import React from 'react';

interface BlockSizeProps {
    size: number;
}

const units = [
  'B', 'KB', 'MB', 'GB', 'TB'
];

export const BlockSize: React.FC<BlockSizeProps> = (props)=>{
    let num = props.size;
    let unitIndex = 0;
    while(num >= 1000 && unitIndex < units.length - 1){
        num /= 1024;
        unitIndex += 1;
    }

    // keep at least 3 effective digits
    if(num < 10)
        num = Math.round(num * 100) / 100;
    else if(num < 100)
        num = Math.round(num * 10) / 10;
    else
        num = Math.round(num);

    return <>{num + units[unitIndex]}</>;
};
