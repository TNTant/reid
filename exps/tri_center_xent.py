import sys

sys.path.insert(0, '/data1/xinglu/prj/open-reid')

from lz import *
import lz
from torch.optim import Optimizer
from torch.backends import cudnn
from torch.utils.data import DataLoader
import reid
from reid import datasets
from reid import models
from reid.models import *
from reid.dist_metric import DistanceMetric
from reid.loss import *
from reid.trainers import *
from reid.evaluators import *
from reid.mining import *
from reid.utils.data import transforms as T
from reid.utils.data.preprocessor import Preprocessor
from reid.utils.data.sampler import *
from reid.utils.serialization import *
from reid.utils.dop import DopInfo

from tensorboardX import SummaryWriter


def run(_):
    cfgs = lz.load_cfg('./cfgs/single_ohnm.py')
    procs = []
    for args in cfgs.cfgs:
        if args.loss != 'tcx' and args.loss != 'tri' and args.loss != 'xent' and args.loss != 'tri_adv':
            print(f'skip {args.loss} {args.logs_dir}')
            continue
        if args.log_at is None:
            args.log_at = np.concatenate([
                range(0, 640, 31),
                range(args.epochs - 8, args.epochs, 1)
            ])
        args.logs_dir = lz.work_path + 'reid/work/' + args.logs_dir
        # if osp.exists(args.logs_dir) and osp.exists(args.logs_dir + '/checkpoint.64.pth'):
        #     print('no exi', os.listdir(args.logs_dir))
        #     continue

        if not args.gpu_fix:
            args.gpu = lz.get_dev(n=len(args.gpu),
                                  ok=args.gpu_range,
                                  )
        lz.logging.info(f'use gpu {args.gpu}')
        # args.batch_size = 16
        # args.gpu = (3, )
        # args.epochs = 1
        # args.logs_dir+='.bak'
        if isinstance(args.gpu, int):
            args.gpu = [args.gpu]
        if not args.evaluate and not args.vis:
            assert args.logs_dir != args.resume
            lz.mkdir_p(args.logs_dir, delete=True)
            lz.pickle_dump(args, args.logs_dir + '/conf.pkl')
        if cfgs.no_proc:
            main(args)
        else:
            proc = mp.Process(target=main, args=(args,))
            proc.start()
            lz.logging.info('next')
            time.sleep(random.randint(39, 90))
            if not cfgs.parallel:
                proc.join()
            else:
                procs.append(proc)

    if cfgs.parallel:
        for proc in procs:
            proc.join()


def get_data2(args):
    (name, split_id,
     data_dir, height, width,
     batch_size, num_instances,
     workers, combine_trainval) = (
        args.dataset, args.split,
        args.data_dir, args.height, args.width,
        args.batch_size, args.num_instances,
        args.workers, args.combine_trainval,)
    pin_memory = args.pin_mem
    name_val = args.dataset_val or args.dataset
    npy = args.has_npy
    rand_ratio = args.random_ratio
    dataset_train = datasets.CUB2('train')
    dataset_test = datasets.CUB2('test')
    normalizer = T.Normalize(mean=[0.485, 0.456, 0.406],
                             std=[0.229, 0.224, 0.225])
    num_classes = np.unique(dataset_train.train_labels).shape[0]
    train_transformer = T.Compose([
        T.ToPILImage(),
        T.RandomCropFlip(height, width, area=args.area),
        T.ToTensor(),
        normalizer,
    ])
    test_transformer = T.Compose([
        T.ToPILImage(),
        T.RectScale(height, width),
        T.ToTensor(),
        normalizer,
    ])


def get_data(args):
    (name, split_id,
     data_dir, height, width,
     batch_size, num_instances,
     workers, combine_trainval) = (
        args.dataset, args.split,
        args.data_dir, args.height, args.width,
        args.batch_size, args.num_instances,
        args.workers, args.combine_trainval,)
    pin_memory = args.pin_mem
    name_val = args.dataset_val or args.dataset
    npy = args.has_npy
    rand_ratio = args.random_ratio
    if isinstance(name, list):
        dataset = datasets.creates(name, split_id=split_id,
                                   cuhk03_classic_split=args.cu03_classic,
                                   args=args
                                   )
    else:
        dataset = datasets.create(name, split_id=split_id,
                                  cuhk03_classic_split=args.cu03_classic,
                                  args=args
                                  )
    dataset_val = datasets.create(name_val, split_id=split_id,
                                  cuhk03_classic_split=args.cu03_classic,
                                  args=args
                                  )
    normalizer = T.Normalize(mean=[0.485, 0.456, 0.406],
                             std=[0.229, 0.224, 0.225])

    train_set = dataset.trainval if combine_trainval else dataset.train
    num_classes = (dataset.num_trainval_ids if combine_trainval
                   else dataset.num_train_ids)

    train_transformer = T.Compose([
        T.RandomCropFlip(height, width, area=args.area),
        T.ToTensor(),
        normalizer,
    ])

    test_transformer = T.Compose([
        T.RectScale(height, width),
        T.ToTensor(),
        normalizer,
    ])
    dop_info = DopInfo(num_classes)
    print('dop info and its id are', dop_info)
    # trainval_t = np.asarray(dataset.trainval, dtype=[('fname', object),
    #                                                  ('pid', int),
    #                                                  ('cid', int)])
    # trainval_t = trainval_t.view(np.recarray)
    # trainval_t = trainval_t[:np.where(trainval_t.pid == 10)[0].min()]

    # trainval_test_loader = DataLoader(Preprocessor(
    #     trainval_t.tolist(),
    #     root=dataset.images_dir,
    #     transform=test_transformer,
    #     has_npy=npy),
    #     batch_size=batch_size, num_workers=workers,
    #     shuffle=False, pin_memory=pin_memory)
    trainval_test_loader = None
    train_loader = DataLoader(
        Preprocessor(train_set, root=dataset.images_dir,
                     transform=train_transformer,
                     has_npy=npy),
        batch_size=batch_size, num_workers=workers,
        sampler=RandomIdentityWeightedSampler(
            train_set, num_instances,
            batch_size=batch_size,
            rand_ratio=rand_ratio,
            dop_info=dop_info,
        ),
        pin_memory=pin_memory, drop_last=True)
    val_loader = DataLoader(
        Preprocessor(dataset_val.val, root=dataset_val.images_dir,
                     transform=test_transformer,
                     has_npy=npy),
        batch_size=batch_size, num_workers=workers,
        shuffle=False, pin_memory=pin_memory)
    query_ga = np.concatenate([
        np.asarray(dataset_val.query).reshape(-1, 3),
        np.asarray(list(set(dataset_val.gallery) - set(dataset_val.query))).reshape(-1, 3)
    ])

    query_ga = np.rec.fromarrays((query_ga[:, 0], query_ga[:, 1].astype(int), query_ga[:, 2].astype(int)),
                                 names=['fnames', 'pids', 'cids'])
    if args.vis:
        pids_chs = np.unique(query_ga.pids)[:10]
        query_ga = query_ga[np.where(np.isin(query_ga.pids, pids_chs))[0]]

    query_ga = query_ga.tolist()
    test_loader = DataLoader(
        Preprocessor(query_ga,
                     root=dataset_val.images_dir,
                     transform=test_transformer,
                     has_npy=npy),
        batch_size=batch_size,  # * 2
        num_workers=workers,
        shuffle=False, pin_memory=False)  # todo for market and dukemtmc do not pin mem, but small dataset pin_mem
    dataset.val = dataset_val.val
    dataset.query = dataset_val.query
    dataset.gallery = dataset_val.gallery
    dataset.images_dir = dataset_val.images_dir
    if args.vis:
        query = np.asarray(dataset.query, dtype=[('fname', object),
                                                 ('pids', int),
                                                 ('cid', int)])
        query = query.view(np.recarray)
        query = query[np.where(np.isin(query.pids, pids_chs))[0]]

        dataset.query = query.tolist()

        gallery = np.asarray(dataset.gallery, dtype=[('fname', object),
                                                     ('pids', int),
                                                     ('cid', int)])
        gallery = gallery.view(np.recarray)
        gallery = gallery[np.where(np.isin(gallery.pids, pids_chs))[0]]

        dataset.gallery = gallery.tolist()

    # dataset.num_val_ids
    return dataset, num_classes, train_loader, val_loader, test_loader, dop_info, trainval_test_loader


def main(args):
    sys.stdout = Logger(osp.join(args.logs_dir, 'log.txt'))
    sys.stderr = Logger(osp.join(args.logs_dir, 'err.txt'))
    lz.init_dev(args.gpu)
    print('config is {}'.format(vars(args)))
    if args.seed is not None:
        np.random.seed(args.seed)
        torch.manual_seed(args.seed)
    cudnn.benchmark = True

    # Create data loaders
    assert args.num_instances > 1, "num_instances should be greater than 1"
    assert args.batch_size % args.num_instances == 0, \
        'num_instances should divide batch_size'

    # if not args.dataset.endwith('2'):
    (dataset, num_classes,
     train_loader, val_loader, test_loader,
     dop_info, trainval_test_loader) = get_data(args)
    # else:
    #     get_data2(args)
    # Create model
    model = models.create(args.arch,
                          dropout=args.dropout,
                          pretrained=args.pretrained,
                          block_name=args.block_name,
                          block_name2=args.block_name2,
                          num_features=args.num_classes,
                          num_classes=1 if 'tri' in args.loss else num_classes,
                          num_deform=args.num_deform,
                          fusion=args.fusion,
                          last_conv_stride=args.last_conv_stride,
                          last_conv_dilation=args.last_conv_dilation,
                          )

    print(model)
    param_mb = sum(p.numel() for p in model.parameters()) / 1000000.0
    print('    Total params: %.2fM' % (param_mb))

    # Load from checkpoint
    start_epoch = best_top1 = 0
    if args.resume:
        while not osp.exists(args.resume):
            lz.logging.warning(' no chkpoint {} '.format(args.resume))
            time.sleep(20)
        if torch.cuda.is_available():
            checkpoint = load_checkpoint(args.resume)
        else:
            checkpoint = load_checkpoint(args.resume, map_location='cpu')
        # model.load_state_dict(checkpoint['state_dict'])
        db_name = args.logs_dir + '/' + args.logs_dir.split('/')[-1] + '.h5'
        load_state_dict(model, checkpoint['state_dict'])
        with lz.Database(db_name) as db:
            if 'cent' in checkpoint:
                db['cent'] = to_numpy(checkpoint['cent'])
            # db['xent'] = to_numpy(checkpoint['state_dict']['embed2.weight']) #todo
        if args.restart:
            start_epoch_ = checkpoint['epoch']
            best_top1_ = checkpoint['best_top1']
            print("=> Start epoch {}  best top1 {:.1%}"
                  .format(start_epoch_, best_top1_))
        else:
            start_epoch = checkpoint['epoch']
            best_top1 = checkpoint['best_top1']
            print("=> Start epoch {}  best top1 {:.1%}"
                  .format(start_epoch, best_top1))
    if args.gpu is None or len(args.gpu) == 0:
        model = nn.DataParallel(model)
    elif len(args.gpu) == 1:
        model = nn.DataParallel(model).cuda()
    else:
        model = nn.DataParallel(model, device_ids=range(len(args.gpu))).cuda()

    # Distance metric
    metric = DistanceMetric(algorithm=args.dist_metric)

    # Evaluator
    evaluator = Evaluator(model, gpu=args.gpu, args=args)
    if args.evaluate:
        # res = evaluator.evaluate(trainval_test_loader, trainval_test_loader.dataset.dataset,
        #                          trainval_test_loader.dataset.dataset, metric, final=True, prefix='train')

        if args.dataset_val != 'stanford_prod' and args.dataset != 'stanford_prod':
            evaluator = Evaluator(model, gpu=args.gpu, args=args)
            res = evaluator.evaluate(test_loader, dataset.query, dataset.gallery, metric,
                                     final=True, prefix='test')
            # res2 = evaluator.evaluate_retrival(test_loader, dataset.query, dataset.gallery)
        else:
            res = evaluator.evaluate_retrival(test_loader, dataset.query, dataset.gallery)

        # res = evaluator.evaluate_recall(test_loader, dataset.query, dataset.gallery)

        lz.logging.info('eval {}'.format(res))
        return res
    # Criterion
    if not args.xent_smooth:
        xent = nn.CrossEntropyLoss()
    else:
        xent = CrossEntropyLabelSmooth(num_classes=num_classes)
    setattr(xent, 'name', 'xent')

    criterion = [
        TripletLoss(
            margin=args.margin, mode=args.tri_mode, args=args) if args.loss == 'tri' else
        TripletLossAdv(
            margin=args.margin, mode=args.tri_mode, args=args),
        CenterLoss(num_classes=num_classes, feat_dim=args.num_classes,
                   margin2=args.margin2,
                   margin3=args.margin3, mode=args.cent_mode,
                   push_scale=args.push_scale,
                   args=args),
        xent]
    if args.gpu is not None:
        criterion = [c.cuda() for c in criterion]
    # Optimizer
    fast_params = []
    for name, param in model.named_parameters():
        if name == 'module.embed1.weight' or name == 'module.embed2.weight':
            fast_params.append(param)
    fast_params_ids = set(map(id, fast_params))
    normal_params = [p for p in model.parameters() if id(p) not in fast_params_ids]
    param_groups = [
        {'params': fast_params, 'lr_mult': args.lr_mult},  # args.lr_mult
        {'params': normal_params, 'lr_mult': 1},
    ]
    if args.optimizer_cent == 'sgd':
        optimizer_cent = torch.optim.SGD(criterion[1].parameters(), lr=args.lr_cent, )
    else:
        optimizer_cent = torch.optim.Adam(criterion[1].parameters(), lr=args.lr_cent, )
    if args.optimizer == 'adam':
        optimizer = torch.optim.Adam(
            # model.parameters(),
            param_groups,
            lr=args.lr,
            betas=args.adam_betas,
            eps=args.adam_eps,  # adam hyperparameter
            weight_decay=args.weight_decay,
            amsgrad=args.amsgrad,
        )
    elif args.optimizer == 'sgd':
        optimizer = torch.optim.SGD(
            # filter(lambda p: p.requires_grad, model.parameters()),
            param_groups,
            lr=args.lr,
            weight_decay=args.weight_decay, momentum=0.9,
            nesterov=False,
        )
    else:
        raise NotImplementedError

    if args.ft_epochs!=0:
        args_cp = copy.deepcopy(args)
        trainer = TriTrainer(model, criterion, dbg=False,
                              logs_at=args_cp.logs_dir + '/ft', args=args_cp)
        for epoch in range(start_epoch, args_cp.ft_epochs):
            hist = trainer.train(epoch, train_loader, optimizer, ft=True)
            save_checkpoint({
                'state_dict': model.module.state_dict(),
                'epoch': epoch + 1,
                'best_top1': best_top1,
            }, True, fpath=osp.join(args.logs_dir,
                                    'checkpoint.{}.pth'.format(epoch))
            )
            print('Finished epoch {:3d} hist {}'.
                  format(epoch, hist))
    
    # Trainer
    if args.loss == 'tcx':
        trainer = TCXTrainer(model, criterion, dbg=True,
                             logs_at=args.logs_dir + '/vis', args=args, dop_info=dop_info)
    elif args.loss == 'tri' or args.loss == 'tri_adv':
        trainer = TriTrainer(model, criterion, dbg=True,
                             logs_at=args.logs_dir + '/vis', args=args, dop_info=dop_info)
    elif args.loss == 'xent':
        trainer = XentTrainer(model, criterion, dbg=True,
                              logs_at=args.logs_dir + '/vis', args=args, dop_info=dop_info)
    else:
        raise NotImplementedError()

    # Schedule learning rate
    def adjust_lr(epoch, optimizer=optimizer, base_lr=args.lr, steps=args.steps, decay=args.decay):

        exp = len(steps)
        for i, step in enumerate(steps):
            if epoch < step:
                exp = i
                break
        lr = base_lr * decay ** exp

        lz.logging.info('use lr {}'.format(lr))
        for param_group in optimizer.param_groups:
            param_group['lr'] = lr * param_group.get('lr_mult', 1)

    def adjust_bs(epoch, args):
        if args.batch_size_l == []:
            return args
        res = 0
        for i, step in enumerate(args.bs_steps):
            if epoch > step:
                res = i + 1
        print(epoch, res)
        if res >= len(args.num_instances_l):
            res = -1
        args.batch_size = args.batch_size_l[res]
        args.num_instances = args.num_instances_l[res]
        return args

    writer = SummaryWriter(args.logs_dir)
    writer.add_scalar('param', param_mb, global_step=0)

    # schedule = CyclicLR(optimizer)
    schedule = None
    # Start training
    
    for epoch in range(start_epoch, args.epochs):
        adjust_lr(epoch=epoch)
        args = adjust_bs(epoch, args)

        hist = trainer.train(epoch, train_loader, optimizer,
                             print_freq=args.print_freq, schedule=schedule,
                             # optimizer_cent=optimizer_cent
                             )
        for k, v in hist.items():
            writer.add_scalar('train/' + k, v, epoch)
        writer.add_scalar('lr', optimizer.param_groups[0]['lr'], epoch)
        writer.add_scalar('bs', args.batch_size, epoch)
        writer.add_scalar('num_instances', args.num_instances, epoch)

        if not args.log_middle:
            continue
        if epoch < args.start_save:
            continue
        if epoch % 9 == 0:
            save_checkpoint({
                'state_dict': model.module.state_dict(),
                'cent': criterion[1].centers,
                'epoch': epoch + 1,
                'best_top1': best_top1,
            }, False, fpath=osp.join(args.logs_dir, 'checkpoint.{}.pth'.format(epoch)))

        if epoch not in args.log_at:
            continue

        save_checkpoint({
            'state_dict': model.module.state_dict(),
            'cent': criterion[1].centers,
            'epoch': epoch + 1,
            'best_top1': best_top1,
        }, False, fpath=osp.join(args.logs_dir, 'checkpoint.{}.pth'.format(epoch)))

        # res = evaluator.evaluate(val_loader, dataset.val, dataset.val, metric)
        # for n, v in res.items():
        #     writer.add_scalar('train/'+n, v, epoch)
        if args.dataset_val != 'stanford_prod' and args.dataset != 'stanford_prod':
            res = evaluator.evaluate(test_loader, dataset.query, dataset.gallery, metric, epoch=epoch)

        else:
            res = evaluator.evaluate_retrival(test_loader, dataset.query, dataset.gallery)

        for n, v in res.items():
            writer.add_scalar('test/' + n, v, epoch)
        top1 = res['top-1']
        is_best = top1 > best_top1
        best_top1 = max(top1, best_top1)
        save_checkpoint({
            'state_dict': model.module.state_dict(),
            'cent': criterion[1].centers,
            'epoch': epoch + 1,
            'best_top1': best_top1,
        }, is_best, fpath=osp.join(args.logs_dir, 'checkpoint.{}.pth'.format(epoch)))  #
        print(res)
        print('\n * Finished epoch {:3d}  top1: {:5.1%}  best: {:5.1%}{}\n'.
              format(epoch, top1, best_top1, ' *' if is_best else ''))
        # break

    # Final test
    # res = evaluator.evaluate(test_loader, dataset.query, dataset.gallery, metric)
    # for n, v in res.items():
    #     writer.add_scalar('test/' + n, v, args.epochs-1)

    if osp.exists(osp.join(args.logs_dir, 'model_best.pth')) and args.test_best:
        print('Test with best model:')
        checkpoint = load_checkpoint(osp.join(args.logs_dir, 'model_best.pth'))
        model.module.load_state_dict(checkpoint['state_dict'])
        metric.train(model, train_loader)
        res = evaluator.evaluate(test_loader, dataset.query, dataset.gallery, metric, final=True)
        for n, v in res.items():
            writer.add_scalar('test/' + n, v, args.epochs + 1)
        lz.logging.info('final eval is {}'.format(res))

    writer.close()
    print(res)
    for k, v in res.items():
        res[k] = float(v)
    json_dump(res, args.logs_dir + '/res.json', 'w')
    return res


if __name__ == '__main__':
    import datetime

    tic = time.time()
    run('')
    toc = time.time()
    print('consume time ', toc - tic)
    if toc - tic > 600:
        mail('tri center xent finish')
    print(datetime.datetime.now().strftime('%D-%H:%M:%S'))
