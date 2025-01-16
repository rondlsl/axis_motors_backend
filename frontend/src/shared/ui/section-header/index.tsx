import styles from "./styles.module.scss";
import { IProps } from "./props";

export const SectionHeader = ({ title }: IProps) => {
  return (
    <div className={"flex items-center gap-4 px-4"}>
      <p className={"text-typeSecondary whitespace-nowrap"}>{title}</p>
      <div className={"w-full h-[0.5px] bg-typeSecondary"} />
    </div>
  );
};
