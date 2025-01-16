import styles from "./styles.module.scss";
import {IProps} from "./props";
import {BannerTitle, PageTitle} from "shared/ui";
import {Earth, Car, PhoneCall, DollarSign} from 'lucide-react'; // добавляем иконку звонка
import classNames from "classnames";

export const BannerHowItWork = (props: IProps) => {
    return (
        <section className={classNames(styles.content, "space-y-14")}>
            <div className={styles.top}>
                <BannerTitle title={"Как это работает"}/>
                <PageTitle
                    title={"Начните зарабатывать на своем авто в 4 шага"}
                    subTitle={""}
                />
            </div>
            <div className={styles.bottom}>
                <div className={styles.item}>
                    <div className={styles.img}>
                        <Car size={48} color="#1572d3"/>
                    </div>
                    <p className={styles.itemTitle}>Добавьте информацию об автомобиле</p>
                    <p className={styles.itemSubtitle}>
                        Укажите дни и время, когда ваш автомобиль доступен для аренды.
                    </p>
                </div>
                <div className={styles.item}>
                    <div className={styles.img}>
                        <PhoneCall size={48} color="#1572d3"/>
                    </div>
                    <p className={styles.itemTitle}>Подтверждение от нашей команды</p>
                    <p className={styles.itemSubtitle}>
                        Наша команда свяжется с вами, чтобы уточнить детали и подтвердить автомобиль для аренды.
                    </p>
                </div>
                <div className={styles.item}>
                    <div className={styles.img}>
                        <Earth size={48} color="#1572d3"/>
                    </div>
                    <p className={styles.itemTitle}>Подключите авто к нашей системе</p>
                    <p className={styles.itemSubtitle}>
                        Установите наши специальные устройтсва, чтобы стать частью системы Azv Motors.
                    </p>
                </div>
                <div className={styles.item}>
                    <div className={styles.img}>
                        <DollarSign size={48} color="#1572d3"/>
                    </div>
                    <p className={styles.itemTitle}>Начните зарабатывать</p>
                    <p className={styles.itemSubtitle}>
                        Получайте доход, когда ваш автомобиль выбирают арендаторы.
                    </p>
                </div>
            </div>
        </section>
    );
};
